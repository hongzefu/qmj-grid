import logging
import math
import time

import util
from game import Agent, Directions
from logs.search_logger import log_function
from pacman import GameState
from util import manhattanDistance


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
        self._search_time_used = 0.0
        self._deadline = None
        self._turn_count = 0
        self._evaluation_cache = {}
        self._successor_cache = {}
        self._position_visits = {}
        self._last_food_count = None
        self._steps_since_food = 0
        self._max_search_depth = self.depth

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
