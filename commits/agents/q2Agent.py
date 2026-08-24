import logging
import math
import random
import time

import util
from game import Actions, Agent, Directions
from logs.search_logger import log_function
from pacman import COLLISION_TOLERANCE, GameState
from util import manhattanDistance, nearestPoint


def scoreEvaluationFunction(currentGameState):
    """
      This default evaluation function just returns the score of the state.
      The score is the same one displayed in the Pacman GUI.

      This evaluation function is meant for use with adversarial search agents
      (not reflex agents).
    """
    return currentGameState.getScore()


def betterEvaluationFunction(currentGameState):
    """Evaluate a state using score, objectives, and ghost safety."""
    score = currentGameState.getScore()

    if currentGameState.isWin():
        return 1_000_000 + score
    if currentGameState.isLose():
        return -1_000_000 + score

    pacman_position = currentGameState.getPacmanPosition()
    food_positions = currentGameState.getFood().asList()
    capsules = currentGameState.getCapsules()
    value = score

    if food_positions:
        nearest_food = min(
            manhattanDistance(pacman_position, food_position)
            for food_position in food_positions
        )
        value -= 4.0 * len(food_positions)
        value -= 1.5 * nearest_food

    if capsules:
        nearest_capsule = min(
            manhattanDistance(pacman_position, capsule)
            for capsule in capsules
        )
        value -= 12.0 * len(capsules)
        value -= 0.5 * nearest_capsule

    for ghost_state in currentGameState.getGhostStates():
        ghost_position = ghost_state.getPosition()
        if ghost_position is None:
            continue

        distance = manhattanDistance(pacman_position, ghost_position)
        if ghost_state.scaredTimer > 0:
            if distance <= ghost_state.scaredTimer:
                value += 80.0 / (distance + 1.0)
        elif distance <= 1:
            value -= 200.0
        elif distance <= 2:
            value -= 60.0
        else:
            value -= 10.0 / distance

    return value


class _SearchTimeout(Exception):
    """Internal signal used to stop an incomplete search iteration."""


class DecisionNode:
    """Pac-Man decision point retained by the MCTS tree."""

    __slots__ = (
        'edges',
        'leaf_value',
        'legal_actions',
        'n',
        'q',
        'state',
        'stats_epoch',
        'untried_actions',
        'w',
    )

    def __init__(self, state, leaf_value, stats_epoch):
        self.state = state
        self.legal_actions = tuple(state.getLegalActions(0))
        current_direction = state.getPacmanState().getDirection()
        indexed_actions = list(enumerate(self.legal_actions))
        indexed_actions.sort(
            key=lambda item: (
                item[1] == Directions.STOP,
                item[1] != current_direction,
                item[0],
            )
        )
        self.untried_actions = [
            (action, original_index)
            for original_index, action in indexed_actions
        ]
        self.edges = []
        self.n = 1
        self.w = leaf_value
        self.q = leaf_value
        self.leaf_value = leaf_value
        self.stats_epoch = stats_epoch


class ActionEdge:
    """A Pac-Man action followed by sampled joint ghost outcomes."""

    __slots__ = (
        'action',
        'ghost_legals',
        'initial_value',
        'minimum',
        'n',
        'original_index',
        'outcomes',
        'pac_state',
        'q',
        'stats_epoch',
        'w',
    )

    def __init__(
        self,
        action,
        original_index,
        pac_state,
        ghost_legals,
        initial_value,
        stats_epoch,
    ):
        self.action = action
        self.original_index = original_index
        self.pac_state = pac_state
        self.ghost_legals = ghost_legals
        self.outcomes = {}
        self.n = 0
        self.w = 0.0
        self.q = initial_value
        self.minimum = 1.0
        self.initial_value = initial_value
        self.stats_epoch = stats_epoch


class Q2_Agent(Agent):

    _TOTAL_SEARCH_BUDGET = 24.0
    _BUDGET_GUARD = 0.05
    _MAX_TURN_BUDGET = 0.35
    _MIN_SEARCH_BUDGET = 0.005

    def __init__(
        self,
        evalFn='betterEvaluationFunction',
        depth='3',
        forcedLossExpectimax='1',
        reactiveFallback='1',
        corridorShortcut='1',
        cycleGuard='1',
        initialBranchingDepthThreshold='64',
        strategy='alphabeta',
        mctsSeed='20250824',
        mctsCpuct='1.0',
        mctsSelect='hybrid',
        mctsPriorTemp='0.5',
        mctsValueScale='100',
        mctsMaxOutcomes='4',
        mctsWidenC='4',
        mctsDeathCorrection='1',
        mctsRiskLambda='0.0',
        mctsTreeReuse='1',
        mctsMaxNodes='20000',
        mctsMaxSims='0',
        mctsIgnoreClock='0',
        mctsTurnBudgetScale='1.0',
        mctsMinPlyBudgetSims='60',
    ):
        self.index = 0  # Pacman is always agent index 0
        self.evaluationFunction = util.lookup(evalFn, globals())
        self.depth = int(depth)
        self._forced_loss_expectimax = bool(int(forcedLossExpectimax))
        self._reactive_fallback_enabled = bool(int(reactiveFallback))
        self._corridor_shortcut_enabled = bool(int(corridorShortcut))
        self._cycle_guard_enabled = bool(int(cycleGuard))
        self._initial_branching_depth_threshold = int(
            initialBranchingDepthThreshold
        )
        self._strategy = strategy.lower()
        self._mcts_seed = int(mctsSeed)
        self._mcts_cpuct = float(mctsCpuct)
        self._mcts_select = mctsSelect.lower()
        self._mcts_prior_temp = float(mctsPriorTemp)
        self._mcts_value_scale = float(mctsValueScale)
        self._mcts_max_outcomes = int(mctsMaxOutcomes)
        self._mcts_widen_c = float(mctsWidenC)
        self._mcts_death_correction = bool(int(mctsDeathCorrection))
        self._mcts_risk_lambda = float(mctsRiskLambda)
        self._mcts_tree_reuse = bool(int(mctsTreeReuse))
        self._mcts_max_nodes = int(mctsMaxNodes)
        self._mcts_max_sims = int(mctsMaxSims)
        self._mcts_ignore_clock = bool(int(mctsIgnoreClock))
        self._mcts_turn_budget_scale = float(mctsTurnBudgetScale)
        self._mcts_min_ply_budget_sims = int(mctsMinPlyBudgetSims)
        self._validate_mcts_options()
        self._search_time_used = 0.0
        self._deadline = None
        self._turn_count = 0
        self._evaluation_cache = {}
        self._successor_cache = {}
        self._position_visits = {}
        self._last_food_count = None
        self._steps_since_food = 0
        self._max_search_depth = self.depth
        self._mcts_rng = random.Random(self._mcts_seed)
        self._mcts_game_count = 0
        self._mcts_force_alphabeta = False
        self._mcts_measured_ply_cost = 0.0
        self._mcts_reuse_candidates = []
        self._mcts_root = None
        self._mcts_anchor = 0.0
        self._mcts_node_count = 0
        self._mcts_stats_epoch = 0
        self._mcts_root_precomputed = {}

    def _validate_mcts_options(self):
        """Reject invalid string-valued agent arguments early."""
        float_options = (
            ('mctsCpuct', self._mcts_cpuct),
            ('mctsPriorTemp', self._mcts_prior_temp),
            ('mctsValueScale', self._mcts_value_scale),
            ('mctsWidenC', self._mcts_widen_c),
            ('mctsRiskLambda', self._mcts_risk_lambda),
            ('mctsTurnBudgetScale', self._mcts_turn_budget_scale),
        )
        for option_name, option_value in float_options:
            if not math.isfinite(option_value):
                raise ValueError(f'{option_name} must be finite')
        if self._strategy not in ('alphabeta', 'mcts'):
            raise ValueError("strategy must be 'alphabeta' or 'mcts'")
        if self._mcts_select not in ('hybrid', 'puct', 'ucb'):
            raise ValueError("mctsSelect must be 'hybrid', 'puct', or 'ucb'")
        if self._mcts_cpuct < 0.0:
            raise ValueError('mctsCpuct must be non-negative')
        if self._mcts_prior_temp <= 0.0:
            raise ValueError('mctsPriorTemp must be positive')
        if self._mcts_value_scale <= 0.0:
            raise ValueError('mctsValueScale must be positive')
        if self._mcts_max_outcomes < 1:
            raise ValueError('mctsMaxOutcomes must be at least 1')
        if self._mcts_widen_c <= 0.0:
            raise ValueError('mctsWidenC must be positive')
        if not 0.0 <= self._mcts_risk_lambda <= 1.0:
            raise ValueError('mctsRiskLambda must be between 0 and 1')
        if self._mcts_max_nodes < 1:
            raise ValueError('mctsMaxNodes must be at least 1')
        if self._mcts_max_sims < 0:
            raise ValueError('mctsMaxSims must be non-negative')
        if self._mcts_ignore_clock and self._mcts_max_sims == 0:
            raise ValueError('mctsIgnoreClock=1 requires mctsMaxSims > 0')
        if self._mcts_turn_budget_scale <= 0.0:
            raise ValueError('mctsTurnBudgetScale must be positive')
        if self._mcts_min_ply_budget_sims < 0:
            raise ValueError('mctsMinPlyBudgetSims must be non-negative')

    def _mcts_turn_budget(self, num_food):
        """Calculate the MCTS budget identically at startup and runtime."""
        remaining_total = max(
            0.0,
            self._TOTAL_SEARCH_BUDGET
            - self._BUDGET_GUARD
            - self._search_time_used,
        )
        expected_remaining_turns = max(
            12,
            math.ceil(1.5 * num_food),
        )
        return min(
            self._MAX_TURN_BUDGET,
            (
                remaining_total / expected_remaining_turns
            ) * self._mcts_turn_budget_scale,
        )

    def registerInitialState(self, gameState: GameState):
        """Reset the cumulative search budget for every new game."""
        self._search_time_used = 0.0
        self._deadline = None
        self._turn_count = 0
        self._position_visits = {}
        self._last_food_count = gameState.getNumFood()
        self._steps_since_food = 0
        self._max_search_depth = self.depth
        if self._initial_branching_depth_threshold > 0:
            joint_branching = len(gameState.getLegalActions(0))
            for ghost_index in range(1, gameState.getNumAgents()):
                joint_branching *= len(
                    gameState.getLegalActions(ghost_index)
                )
            if joint_branching > self._initial_branching_depth_threshold:
                self._max_search_depth = min(self.depth, 2)

        if self._strategy == 'mcts':
            self._mcts_game_count += 1
            self._mcts_rng.seed(
                self._mcts_seed * 1_000_003 + self._mcts_game_count
            )
            self._mcts_reuse_candidates = []
            self._mcts_root = None
            self._mcts_node_count = 0
            self._mcts_force_alphabeta = False
            if (
                self._mcts_min_ply_budget_sims > 0
                and not self._mcts_ignore_clock
            ):
                self._mcts_measured_ply_cost = self._measure_mcts_ply_cost(
                    gameState
                )
                initial_turn_budget = self._mcts_turn_budget(
                    gameState.getNumFood()
                )
                # A growing simulation traverses old and new decision plies.
                estimated_simulations = (
                    initial_turn_budget
                    / (2.0 * self._mcts_measured_ply_cost)
                    if self._mcts_measured_ply_cost > 0.0
                    else float('inf')
                )
                self._mcts_force_alphabeta = (
                    estimated_simulations < self._mcts_min_ply_budget_sims
                )

    def _measure_mcts_ply_cost(self, gameState):
        """Estimate one Pac-Man-plus-ghost ply from about 20 successors."""
        pacman_actions = gameState.getLegalActions(0)
        if not pacman_actions:
            return 0.0

        successor_count = 0
        completed_plies = 0
        action_index = 0
        start_time = time.perf_counter()
        while successor_count < 20:
            action = pacman_actions[action_index % len(pacman_actions)]
            action_index += 1
            state = gameState.generateSuccessor(0, action)
            successor_count += 1
            for ghost_index in range(1, state.getNumAgents()):
                if state.isWin() or state.isLose():
                    break
                ghost_actions = state.getLegalActions(ghost_index)
                if not ghost_actions:
                    continue
                state = state.generateSuccessor(
                    ghost_index,
                    ghost_actions[0],
                )
                successor_count += 1
                if successor_count >= 20:
                    break
            self.evaluationFunction(state)
            completed_plies += 1

        elapsed = time.perf_counter() - start_time
        return elapsed / max(1, completed_plies)

    def _check_deadline(self):
        if self._deadline is not None and time.perf_counter() >= self._deadline:
            raise _SearchTimeout()

    def _evaluate(self, gameState):
        """Cache pure state evaluations during one getAction call."""
        if gameState not in self._evaluation_cache:
            self._evaluation_cache[gameState] = self.evaluationFunction(gameState)
        return self._evaluation_cache[gameState]

    def _ghost_ordering_value(self, gameState):
        """Preserve ghost ordering without rescanning unchanged objectives."""
        score = gameState.getScore()
        if gameState.isWin():
            return 1_000_000 + score
        if gameState.isLose():
            return -1_000_000 + score

        pacman_position = gameState.getPacmanPosition()
        value = score
        for ghost_state in gameState.getGhostStates():
            ghost_position = ghost_state.getPosition()
            if ghost_position is None:
                continue

            distance = manhattanDistance(pacman_position, ghost_position)
            if ghost_state.scaredTimer > 0:
                if distance <= ghost_state.scaredTimer:
                    value += 80.0 / (distance + 1.0)
            elif distance <= 1:
                value -= 200.0
            elif distance <= 2:
                value -= 60.0
            else:
                value -= 10.0 / distance

        return value

    @staticmethod
    def _tie_key(action, original_index):
        """Prefer moving over STOP, then preserve the legal-action order."""
        return action == Directions.STOP, original_index

    def _ordered_successors(self, gameState, agent_index, preferred_action=None):
        """Generate each successor once and order it to improve pruning."""
        self._check_deadline()
        cache_key = (gameState, agent_index)
        if cache_key not in self._successor_cache:
            actions = gameState.getLegalActions(agent_index)
            successors = []

            for original_index, action in enumerate(actions):
                self._check_deadline()
                successor = gameState.generateSuccessor(agent_index, action)
                if (
                    agent_index > 0
                    and self.evaluationFunction is betterEvaluationFunction
                ):
                    ordering_value = self._ghost_ordering_value(successor)
                else:
                    ordering_value = self._evaluate(successor)
                successors.append(
                    (action, successor, original_index, ordering_value)
                )
            self._successor_cache[cache_key] = tuple(successors)

        successors = list(self._successor_cache[cache_key])
        if agent_index == 0:
            successors.sort(
                key=lambda item: (
                    0 if item[0] == preferred_action else 1,
                    item[0] == Directions.STOP,
                    -item[3],
                    item[2],
                )
            )
        else:
            successors.sort(key=lambda item: (item[3], item[2]))

        return successors

    def _fallback_action(self, gameState, legal_actions):
        """Return a deterministic legal action even if search cannot finish."""
        best_action = legal_actions[0]
        best_value = -float('inf')
        best_tie_key = self._tie_key(best_action, 0)

        for original_index, action in enumerate(legal_actions):
            self._check_deadline()
            successor = gameState.generateSuccessor(0, action)
            value = self._evaluate(successor)
            tie_key = self._tie_key(action, original_index)
            if value > best_value or (
                value == best_value and tie_key < best_tie_key
            ):
                best_action = action
                best_value = value
                best_tie_key = tie_key

        return best_action

    def _safe_corridor_action(self, gameState, legal_actions):
        """Continue through a safe straight corridor without spending search."""
        if not self._corridor_shortcut_enabled:
            return None

        current_position = gameState.getPacmanPosition()
        if self._cycle_guard_enabled and (
            self._position_visits.get(current_position, 0) > 1
            or self._steps_since_food > 12
        ):
            return None

        non_stop_actions = [
            action for action in legal_actions if action != Directions.STOP
        ]
        current_direction = gameState.getPacmanState().getDirection()
        if (
            len(non_stop_actions) != 2
            or current_direction not in non_stop_actions
        ):
            return None

        pacman_position = gameState.getPacmanPosition()
        active_distances = [
            manhattanDistance(pacman_position, ghost_state.getPosition())
            for ghost_state in gameState.getGhostStates()
            if (
                ghost_state.scaredTimer <= 1
                and ghost_state.getPosition() is not None
            )
        ]
        if active_distances and min(active_distances) <= 6:
            return None
        return current_direction

    def _simple_fallback(self, gameState, legal_actions):
        """Return a cheap legal move, preferring progress over revisits."""
        if not self._cycle_guard_enabled:
            return next(
                (
                    action
                    for action in legal_actions
                    if action != Directions.STOP
                ),
                legal_actions[0],
            )

        current_food = gameState.getNumFood()
        best_action = legal_actions[0]
        best_key = None
        for original_index, action in enumerate(legal_actions):
            successor = gameState.generateSuccessor(0, action)
            key = (
                successor.isWin(),
                not successor.isLose(),
                successor.getNumFood() < current_food,
                -self._position_visits.get(
                    successor.getPacmanPosition(),
                    0,
                ),
                action != Directions.STOP,
                -original_index,
            )
            if best_key is None or key > best_key:
                best_action = action
                best_key = key
        return best_action

    def _reactive_fallback(self, gameState, legal_actions):
        """Prefer moves with fewer immediately lethal ghost replies."""
        best_action = legal_actions[0]
        best_key = None

        for original_index, action in enumerate(legal_actions):
            self._check_deadline()
            successor = gameState.generateSuccessor(0, action)
            unsafe_replies = 0
            if successor.isLose():
                unsafe_replies = 1_000_000
            elif not successor.isWin():
                for ghost_index in range(1, successor.getNumAgents()):
                    for ghost_action in successor.getLegalActions(ghost_index):
                        self._check_deadline()
                        ghost_successor = successor.generateSuccessor(
                            ghost_index,
                            ghost_action,
                        )
                        if ghost_successor.isLose():
                            unsafe_replies += 1

            key = (
                successor.isWin(),
                -unsafe_replies,
                self._evaluate(successor),
                action != Directions.STOP,
                -original_index,
            )
            if best_key is None or key > best_key:
                best_action = action
                best_key = key

        return best_action

    def _alphabeta(self, gameState, agent_index, rounds_left, alpha, beta):
        self._check_deadline()

        if (
            gameState.isWin()
            or gameState.isLose()
            or rounds_left <= 0
        ):
            return self._evaluate(gameState)

        successors = self._ordered_successors(gameState, agent_index)
        if not successors:
            return self._evaluate(gameState)

        num_agents = gameState.getNumAgents()
        next_agent = (agent_index + 1) % num_agents
        next_rounds = rounds_left - 1 if next_agent == 0 else rounds_left

        if agent_index == 0:
            value = -float('inf')
            for _, successor, _, _ in successors:
                value = max(
                    value,
                    self._alphabeta(
                        successor,
                        next_agent,
                        next_rounds,
                        alpha,
                        beta,
                    ),
                )
                if value >= beta:
                    return value
                alpha = max(alpha, value)
            return value

        value = float('inf')
        for _, successor, _, _ in successors:
            value = min(
                value,
                self._alphabeta(
                    successor,
                    next_agent,
                    next_rounds,
                    alpha,
                    beta,
                ),
            )
            if value <= alpha:
                return value
            beta = min(beta, value)
        return value

    def _search_root(self, gameState, depth, preferred_action):
        self._check_deadline()
        successors = self._ordered_successors(
            gameState,
            0,
            preferred_action=preferred_action,
        )
        if not successors:
            return Directions.STOP, self._evaluate(gameState)

        num_agents = gameState.getNumAgents()
        next_agent = 1 % num_agents
        rounds_left = depth - 1 if next_agent == 0 else depth
        alpha = -float('inf')
        beta = float('inf')
        best_action = successors[0][0]
        best_value = -float('inf')
        best_tie_key = self._tie_key(
            successors[0][0],
            successors[0][2],
        )

        for action, successor, original_index, _ in successors:
            self._check_deadline()
            value = self._alphabeta(
                successor,
                next_agent,
                rounds_left,
                alpha,
                beta,
            )
            tie_key = self._tie_key(action, original_index)
            if value > best_value or (
                value == best_value and tie_key < best_tie_key
            ):
                best_action = action
                best_value = value
                best_tie_key = tie_key
            alpha = max(alpha, best_value)

        return best_action, best_value

    def _expectimax(self, gameState, agent_index, rounds_left):
        """Evaluate random ghosts only after alpha-beta proves a loss."""
        self._check_deadline()
        if (
            gameState.isWin()
            or gameState.isLose()
            or rounds_left <= 0
        ):
            return self._evaluate(gameState)

        successors = self._ordered_successors(gameState, agent_index)
        if not successors:
            return self._evaluate(gameState)

        num_agents = gameState.getNumAgents()
        next_agent = (agent_index + 1) % num_agents
        next_rounds = rounds_left - 1 if next_agent == 0 else rounds_left
        values = [
            self._expectimax(successor, next_agent, next_rounds)
            for _, successor, _, _ in successors
        ]
        if agent_index == 0:
            return max(values)
        return sum(values) / len(values)

    def _search_root_expectimax(self, gameState, depth, preferred_action):
        """Choose an expected action at a completed alpha-beta depth."""
        successors = self._ordered_successors(
            gameState,
            0,
            preferred_action=preferred_action,
        )
        num_agents = gameState.getNumAgents()
        next_agent = 1 % num_agents
        rounds_left = depth - 1 if next_agent == 0 else depth
        best_action = successors[0][0]
        best_value = -float('inf')
        best_tie_key = self._tie_key(best_action, successors[0][2])

        for action, successor, original_index, _ in successors:
            value = self._expectimax(
                successor,
                next_agent,
                rounds_left,
            )
            tie_key = self._tie_key(action, original_index)
            if value > best_value or (
                value == best_value and tie_key < best_tie_key
            ):
                best_action = action
                best_value = value
                best_tie_key = tie_key

        return best_action, best_value

    @staticmethod
    def _mcts_state_signature(gameState):
        """Build a cheap signature before an exact tree-reuse comparison."""
        ghosts = tuple(
            (
                ghost_state.getPosition(),
                ghost_state.getDirection(),
                ghost_state.scaredTimer,
            )
            for ghost_state in gameState.getGhostStates()
        )
        return (
            gameState.getPacmanPosition(),
            ghosts,
            gameState.getNumFood(),
        )

    def _death_prob(self, gameState, ghost_legals=None):
        """Compute the exact one-step lethal probability without successors."""
        if gameState.isWin() or gameState.isLose():
            return 0.0

        pacman_position = gameState.getPacmanPosition()
        survival_probability = 1.0
        for ghost_offset, ghost_state in enumerate(
            gameState.getGhostStates()
        ):
            timer = ghost_state.scaredTimer
            if timer > 1:
                continue

            ghost_position = ghost_state.getPosition()
            if ghost_position is None:
                continue
            ghost_index = ghost_offset + 1
            if ghost_legals is None:
                legal_actions = gameState.getLegalActions(ghost_index)
            else:
                legal_actions = ghost_legals[ghost_offset]
            if not legal_actions:
                continue

            lethal_actions = 0
            speed = 0.5 if timer == 1 else 1.0
            for action in legal_actions:
                dx, dy = Actions.directionToVector(action, speed)
                next_position = (
                    ghost_position[0] + dx,
                    ghost_position[1] + dy,
                )
                if timer == 1:
                    next_position = nearestPoint(next_position)
                if (
                    manhattanDistance(next_position, pacman_position)
                    <= COLLISION_TOLERANCE
                ):
                    lethal_actions += 1

            lethal_probability = lethal_actions / len(legal_actions)
            survival_probability *= 1.0 - lethal_probability

        return 1.0 - survival_probability

    def _mcts_leaf_value(self, gameState, ghost_legals=None):
        """Map the evaluation function to a bounded MCTS leaf value."""
        if gameState.isWin():
            return 1.0
        if gameState.isLose():
            return 0.0

        evaluation = self.evaluationFunction(gameState)
        value = 0.5 + 0.5 * math.tanh(
            (evaluation - self._mcts_anchor) / self._mcts_value_scale
        )
        if self._mcts_death_correction:
            value *= 1.0 - self._death_prob(
                gameState,
                ghost_legals=ghost_legals,
            )
        return value

    def _mcts_new_node(self, gameState):
        """Create a value-initialised decision node for the current epoch."""
        node = DecisionNode(
            gameState,
            self._mcts_leaf_value(gameState),
            self._mcts_stats_epoch,
        )
        self._mcts_node_count += 1
        return node

    def _mcts_refresh_node(self, node):
        """Lazily reset reused statistics for the current root anchor."""
        if node.stats_epoch == self._mcts_stats_epoch:
            return

        leaf_value = self._mcts_leaf_value(node.state)
        node.n = 1
        node.w = leaf_value
        node.q = leaf_value
        node.leaf_value = leaf_value
        node.stats_epoch = self._mcts_stats_epoch
        for edge in node.edges:
            initial_value = self._mcts_leaf_value(
                edge.pac_state,
                ghost_legals=edge.ghost_legals,
            )
            edge.n = 0
            edge.w = 0.0
            edge.q = initial_value
            edge.minimum = 1.0
            edge.initial_value = initial_value
            edge.stats_epoch = self._mcts_stats_epoch

    def _mcts_restore_root(self, gameState):
        """Reuse an exactly matching child while avoiding GameState hashing."""
        reuse_candidates = self._mcts_reuse_candidates
        self._mcts_reuse_candidates = []
        if self._mcts_tree_reuse:
            signature = self._mcts_state_signature(gameState)
            for candidate_signature, candidate in reuse_candidates:
                if (
                    candidate_signature == signature
                    and candidate.state == gameState
                ):
                    candidate.state = gameState
                    self._mcts_root = candidate
                    self._mcts_refresh_node(candidate)
                    return candidate

        self._mcts_node_count = 0
        self._mcts_root = self._mcts_new_node(gameState)
        return self._mcts_root

    def _mcts_expand_action(self, node):
        """Expand one Pac-Man action and cache its ghost action sets."""
        action, original_index = node.untried_actions[0]
        self._check_deadline()
        precomputed = (
            self._mcts_root_precomputed.get(action)
            if node is self._mcts_root
            else None
        )
        if precomputed is None:
            pac_state = node.state.generateSuccessor(0, action)
            if pac_state.isWin() or pac_state.isLose():
                ghost_legals = ()
            else:
                ghost_legals = tuple(
                    tuple(pac_state.getLegalActions(ghost_index))
                    for ghost_index in range(1, pac_state.getNumAgents())
                )
            initial_value = self._mcts_leaf_value(
                pac_state,
                ghost_legals=ghost_legals,
            )
        else:
            pac_state, ghost_legals, initial_value = precomputed

        edge = ActionEdge(
            action,
            original_index,
            pac_state,
            ghost_legals,
            initial_value,
            self._mcts_stats_epoch,
        )
        node.edges.append(edge)
        node.untried_actions.pop(0)
        return edge, initial_value

    def _mcts_edge_priors(self, edges):
        """Softmax the expanded child leaf values into PUCT priors."""
        scaled_values = [
            edge.initial_value / self._mcts_prior_temp
            for edge in edges
        ]
        maximum = max(scaled_values)
        weights = [math.exp(value - maximum) for value in scaled_values]
        total = sum(weights)
        return [weight / total for weight in weights]

    def _mcts_select_edge(self, node, is_root):
        """Select a Pac-Man action with root PUCT or internal UCB1."""
        use_puct = self._mcts_select == 'puct' or (
            self._mcts_select == 'hybrid' and is_root
        )
        priors = (
            self._mcts_edge_priors(node.edges)
            if use_puct
            else [0.0] * len(node.edges)
        )
        best_edge = node.edges[0]
        best_key = None
        for edge, prior in zip(node.edges, priors):
            if use_puct:
                exploration = (
                    self._mcts_cpuct
                    * prior
                    * math.sqrt(max(1, node.n))
                    / (1 + edge.n)
                )
            elif edge.n == 0:
                exploration = float('inf')
            else:
                exploration = self._mcts_cpuct * math.sqrt(
                    math.log(max(2, node.n)) / edge.n
                )
            key = (
                edge.q + exploration,
                edge.action != Directions.STOP,
                -edge.original_index,
            )
            if best_key is None or key > best_key:
                best_edge = edge
                best_key = key
        return best_edge

    def _mcts_sample_joint_action(self, edge):
        """Sample independent uniform ghost actions with the private RNG."""
        sampled_actions = []
        for legal_actions in edge.ghost_legals:
            if legal_actions:
                sampled_actions.append(
                    legal_actions[
                        self._mcts_rng.randrange(len(legal_actions))
                    ]
                )
            else:
                sampled_actions.append(None)
        return tuple(sampled_actions)

    def _mcts_outcome_limit(self, edge):
        """Return the progressive-widening limit for a chance edge."""
        widened = 1 + math.floor(
            math.sqrt(edge.n / self._mcts_widen_c)
        )
        return min(self._mcts_max_outcomes, widened)

    def _mcts_apply_joint_action(self, edge, joint_action):
        """Apply a sampled joint ghost action until a terminal state."""
        state = edge.pac_state
        for ghost_index, ghost_action in enumerate(
            joint_action,
            start=1,
        ):
            if state.isWin() or state.isLose():
                break
            if ghost_action is None:
                continue
            self._check_deadline()
            state = state.generateSuccessor(ghost_index, ghost_action)
        return state

    def _mcts_chance_child(self, edge):
        """Reuse, widen, or resample a joint ghost outcome."""
        joint_action = self._mcts_sample_joint_action(edge)
        child = edge.outcomes.get(joint_action)
        if child is not None:
            return child, False

        if (
            len(edge.outcomes) < self._mcts_outcome_limit(edge)
            and self._mcts_node_count < self._mcts_max_nodes
        ):
            child_state = self._mcts_apply_joint_action(
                edge,
                joint_action,
            )
            child = self._mcts_new_node(child_state)
            edge.outcomes[joint_action] = child
            return child, True

        if edge.outcomes:
            existing_actions = tuple(edge.outcomes)
            selected_action = existing_actions[
                self._mcts_rng.randrange(len(existing_actions))
            ]
            return edge.outcomes[selected_action], False
        return None, False

    def _mcts_backpropagate(self, visited_nodes, path, value):
        """Back up one bounded leaf value through decision and chance stats."""
        for node in visited_nodes:
            node.n += 1
            node.w += value
            node.q = node.w / node.n
        for edge in path:
            edge.n += 1
            edge.w += value
            edge.minimum = min(edge.minimum, value)
            mean_value = edge.w / edge.n
            edge.q = (
                (1.0 - self._mcts_risk_lambda) * mean_value
                + self._mcts_risk_lambda * edge.minimum
            )

    def _mcts_simulation(self, root):
        """Run one selection, lazy expansion, chance, and backup cycle."""
        node = root
        visited_nodes = [root]
        path = []
        while True:
            self._mcts_refresh_node(node)
            if node.state.isWin() or node.state.isLose():
                value = self._mcts_leaf_value(node.state)
                self._mcts_backpropagate(visited_nodes, path, value)
                return

            if node.untried_actions:
                edge, value = self._mcts_expand_action(node)
                path.append(edge)
                self._mcts_backpropagate(visited_nodes, path, value)
                return

            if not node.edges:
                value = self._mcts_leaf_value(node.state)
                self._mcts_backpropagate(visited_nodes, path, value)
                return

            edge = self._mcts_select_edge(node, node is root)
            path.append(edge)
            if edge.pac_state.isWin() or edge.pac_state.isLose():
                value = self._mcts_leaf_value(edge.pac_state)
                self._mcts_backpropagate(visited_nodes, path, value)
                return

            child, is_new = self._mcts_chance_child(edge)
            if child is None:
                value = edge.initial_value
                self._mcts_backpropagate(visited_nodes, path, value)
                return
            if is_new:
                self._mcts_backpropagate(
                    visited_nodes,
                    path,
                    child.leaf_value,
                )
                return

            node = child
            visited_nodes.append(child)

    def _mcts_best_edge(self, root):
        """Choose the robust child with deterministic legal-order ties."""
        if not root.edges:
            return None
        return max(
            root.edges,
            key=lambda edge: (
                edge.pac_state.isWin(),
                not edge.pac_state.isLose(),
                edge.n,
                edge.q,
                edge.action != Directions.STOP,
                -edge.original_index,
            ),
        )

    def _mcts_remember_outcomes(self, edge):
        """Retain only the selected action's possible next decision points."""
        if not self._mcts_tree_reuse or edge is None:
            self._mcts_reuse_candidates = []
            return
        self._mcts_reuse_candidates = [
            (self._mcts_state_signature(node.state), node)
            for node in edge.outcomes.values()
        ]

    def _mcts_fallback_action(self, gameState, legal_actions, root):
        """Evaluate each root successor once and retain it for expansion."""
        edge_by_action = {edge.action: edge for edge in root.edges}
        best_action = legal_actions[0]
        best_value = -float('inf')
        best_tie_key = self._tie_key(best_action, 0)
        self._mcts_root_precomputed = {}

        for original_index, action in enumerate(legal_actions):
            existing_edge = edge_by_action.get(action)
            if existing_edge is None:
                pac_state = gameState.generateSuccessor(0, action)
                if pac_state.isWin() or pac_state.isLose():
                    ghost_legals = ()
                else:
                    ghost_legals = tuple(
                        tuple(pac_state.getLegalActions(ghost_index))
                        for ghost_index in range(
                            1,
                            pac_state.getNumAgents(),
                        )
                    )
                value = self._mcts_leaf_value(
                    pac_state,
                    ghost_legals=ghost_legals,
                )
            else:
                pac_state = existing_edge.pac_state
                ghost_legals = existing_edge.ghost_legals
                value = existing_edge.initial_value
            self._mcts_root_precomputed[action] = (
                pac_state,
                ghost_legals,
                value,
            )

            tie_key = self._tie_key(action, original_index)
            if value > best_value or (
                value == best_value and tie_key < best_tie_key
            ):
                best_action = action
                best_value = value
                best_tie_key = tie_key
        return best_action

    def _mcts_reactive_fallback(self, gameState, legal_actions):
        """Choose a direct-evaluation move with few lethal ghost replies."""
        best_action = legal_actions[0]
        best_key = None
        for original_index, action in enumerate(legal_actions):
            self._check_deadline()
            successor = gameState.generateSuccessor(0, action)
            unsafe_replies = 0
            if successor.isLose():
                unsafe_replies = 1_000_000
            elif not successor.isWin():
                for ghost_index in range(1, successor.getNumAgents()):
                    for ghost_action in successor.getLegalActions(
                        ghost_index
                    ):
                        self._check_deadline()
                        ghost_successor = successor.generateSuccessor(
                            ghost_index,
                            ghost_action,
                        )
                        if ghost_successor.isLose():
                            unsafe_replies += 1

            key = (
                successor.isWin(),
                -unsafe_replies,
                self.evaluationFunction(successor),
                action != Directions.STOP,
                -original_index,
            )
            if best_key is None or key > best_key:
                best_action = action
                best_key = key
        return best_action

    def _get_mcts_action(self, gameState):
        """Return an anytime MCTS action without touching global randomness."""
        logger = logging.getLogger('root')
        logger.info('MCTSAgent')
        start_time = time.perf_counter()

        try:
            legal_actions = gameState.getLegalActions(0)
            if not legal_actions:
                return Directions.STOP

            emergency_action = next(
                (
                    action
                    for action in legal_actions
                    if action != Directions.STOP
                ),
                legal_actions[0],
            )
            if (
                not self._mcts_ignore_clock
                and self._search_time_used >= 27.0
            ):
                return emergency_action

            current_food = gameState.getNumFood()
            current_position = gameState.getPacmanPosition()
            if (
                self._last_food_count is None
                or current_food < self._last_food_count
            ):
                self._position_visits = {}
                self._steps_since_food = 0
            else:
                self._steps_since_food += 1
            self._position_visits[current_position] = (
                self._position_visits.get(current_position, 0) + 1
            )
            self._last_food_count = current_food

            corridor_action = self._safe_corridor_action(
                gameState,
                legal_actions,
            )
            if corridor_action is not None:
                self._mcts_reuse_candidates = []
                return corridor_action

            fallback_action = emergency_action
            turn_budget = self._mcts_turn_budget(
                gameState.getNumFood()
            )

            if (
                not self._mcts_ignore_clock
                and turn_budget < self._MIN_SEARCH_BUDGET
            ):
                fallback_action = self._simple_fallback(
                    gameState,
                    legal_actions,
                )
                if (
                    self._reactive_fallback_enabled
                    and self._search_time_used < 27.0
                ):
                    self._deadline = start_time + min(
                        0.003,
                        27.0 - self._search_time_used,
                    )
                    try:
                        return self._mcts_reactive_fallback(
                            gameState,
                            legal_actions,
                        )
                    except _SearchTimeout:
                        pass
                return fallback_action

            self._deadline = (
                None
                if self._mcts_ignore_clock
                else start_time + turn_budget
            )
            self._mcts_anchor = self.evaluationFunction(gameState)
            self._mcts_stats_epoch += 1
            root = self._mcts_restore_root(gameState)
            try:
                fallback_action = self._mcts_fallback_action(
                    gameState,
                    legal_actions,
                    root,
                )
            except _SearchTimeout:
                return fallback_action

            simulations = 0
            simulation_ema = None
            while (
                self._mcts_max_sims == 0
                or simulations < self._mcts_max_sims
            ):
                if self._deadline is not None:
                    now = time.perf_counter()
                    if now >= self._deadline:
                        break
                    if (
                        simulation_ema is not None
                        and now + 1.2 * simulation_ema >= self._deadline
                    ):
                        break

                simulation_start = time.perf_counter()
                try:
                    self._mcts_simulation(root)
                except _SearchTimeout:
                    break
                simulation_time = (
                    time.perf_counter() - simulation_start
                )
                simulation_ema = (
                    simulation_time
                    if simulation_ema is None
                    else 0.8 * simulation_ema + 0.2 * simulation_time
                )
                simulations += 1

            best_edge = self._mcts_best_edge(root)
            if best_edge is None or root.untried_actions:
                return fallback_action
            self._mcts_remember_outcomes(best_edge)
            return best_edge.action
        finally:
            self._search_time_used += time.perf_counter() - start_time
            self._turn_count += 1
            self._deadline = None

    @log_function
    def getAction(self, gameState: GameState):
        """
            Returns an alpha-beta action from the current gameState using
            iterative deepening up to self.depth.

            Here are some method calls that might be useful when implementing minimax.

            gameState.getLegalActions(agentIndex):
            Returns a list of legal actions for an agent
            agentIndex=0 means Pacman, ghosts are >= 1

            gameState.generateSuccessor(agentIndex, action):
            Returns the successor game state after an agent takes an action

            gameState.getNumAgents():
            Returns the total number of agents in the game
        """
        if self._strategy == 'mcts' and not self._mcts_force_alphabeta:
            return self._get_mcts_action(gameState)

        logger = logging.getLogger('root')
        logger.info('AlphaBetaAgent')
        start_time = time.perf_counter()
        self._evaluation_cache = {}
        self._successor_cache = {}

        try:
            legal_actions = gameState.getLegalActions(0)
            if not legal_actions:
                return Directions.STOP

            emergency_action = next(
                (
                    action
                    for action in legal_actions
                    if action != Directions.STOP
                ),
                legal_actions[0],
            )
            if self._search_time_used >= 27.0:
                return emergency_action

            current_food = gameState.getNumFood()
            current_position = gameState.getPacmanPosition()
            if (
                self._last_food_count is None
                or current_food < self._last_food_count
            ):
                self._position_visits = {}
                self._steps_since_food = 0
            else:
                self._steps_since_food += 1
            self._position_visits[current_position] = (
                self._position_visits.get(current_position, 0) + 1
            )
            self._last_food_count = current_food

            corridor_action = self._safe_corridor_action(
                gameState,
                legal_actions,
            )
            if corridor_action is not None:
                fallback_action = corridor_action
            else:
                fallback_action = self._simple_fallback(
                    gameState,
                    legal_actions,
                )
            best_action = fallback_action

            remaining_total = max(
                0.0,
                self._TOTAL_SEARCH_BUDGET
                - self._BUDGET_GUARD
                - self._search_time_used,
            )
            expected_remaining_turns = max(
                12,
                math.ceil(1.5 * gameState.getNumFood()),
            )
            turn_budget = min(
                self._MAX_TURN_BUDGET,
                remaining_total / expected_remaining_turns,
            )

            if turn_budget < self._MIN_SEARCH_BUDGET:
                if (
                    self._reactive_fallback_enabled
                    and self._search_time_used < 27.0
                ):
                    self._deadline = start_time + min(
                        0.003,
                        27.0 - self._search_time_used,
                    )
                    try:
                        return self._reactive_fallback(
                            gameState,
                            legal_actions,
                        )
                    except _SearchTimeout:
                        pass
                return fallback_action

            self._deadline = start_time + turn_budget
            try:
                fallback_action = self._fallback_action(
                    gameState,
                    legal_actions,
                )
            except _SearchTimeout:
                return best_action

            best_action = fallback_action
            preferred_action = fallback_action
            best_value = -float('inf')
            completed_depth = 0

            for depth in range(1, self._max_search_depth + 1):
                try:
                    completed_action, completed_value = self._search_root(
                        gameState,
                        depth,
                        preferred_action,
                    )
                except _SearchTimeout:
                    break

                best_action = completed_action
                best_value = completed_value
                preferred_action = completed_action
                completed_depth = depth

                if (
                    depth == 1
                    and corridor_action is not None
                    and completed_value > -900_000
                ):
                    return corridor_action

            if (
                self._forced_loss_expectimax
                and self.evaluationFunction is betterEvaluationFunction
                and completed_depth > 0
                and best_value <= -900_000
            ):
                try:
                    expected_action, _ = self._search_root_expectimax(
                        gameState,
                        completed_depth,
                        best_action,
                    )
                    return expected_action
                except _SearchTimeout:
                    pass

            return best_action
        finally:
            self._search_time_used += time.perf_counter() - start_time
            self._turn_count += 1
            self._deadline = None
