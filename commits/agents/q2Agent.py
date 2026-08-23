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

    def __init__(self, evalFn='betterEvaluationFunction', depth='3'):
        self.index = 0  # Pacman is always agent index 0
        self.evaluationFunction = util.lookup(evalFn, globals())
        self.depth = int(depth)
        self._search_time_used = 0.0
        self._deadline = None
        self._turn_count = 0

    def registerInitialState(self, gameState: GameState):
        """Reset the cumulative search budget for every new game."""
        self._search_time_used = 0.0
        self._deadline = None
        self._turn_count = 0

    def _check_deadline(self):
        if self._deadline is not None and time.perf_counter() >= self._deadline:
            raise _SearchTimeout()

    @staticmethod
    def _tie_key(action, original_index):
        """Prefer moving over STOP, then preserve the legal-action order."""
        return action == Directions.STOP, original_index

    def _ordered_successors(self, gameState, agent_index, preferred_action=None):
        """Generate each successor once and order it to improve pruning."""
        self._check_deadline()
        actions = gameState.getLegalActions(agent_index)
        successors = []

        for original_index, action in enumerate(actions):
            self._check_deadline()
            successor = gameState.generateSuccessor(agent_index, action)
            ordering_value = self.evaluationFunction(successor)
            successors.append(
                (action, successor, original_index, ordering_value)
            )

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
            value = self.evaluationFunction(successor)
            tie_key = self._tie_key(action, original_index)
            if value > best_value or (
                value == best_value and tie_key < best_tie_key
            ):
                best_action = action
                best_value = value
                best_tie_key = tie_key

        return best_action

    def _alphabeta(self, gameState, agent_index, rounds_left, alpha, beta):
        self._check_deadline()

        if (
            gameState.isWin()
            or gameState.isLose()
            or rounds_left <= 0
        ):
            return self.evaluationFunction(gameState)

        successors = self._ordered_successors(gameState, agent_index)
        if not successors:
            return self.evaluationFunction(gameState)

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
            return Directions.STOP, self.evaluationFunction(gameState)

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

        try:
            legal_actions = gameState.getLegalActions(0)
            if not legal_actions:
                return Directions.STOP

            fallback_action = next(
                (
                    action
                    for action in legal_actions
                    if action != Directions.STOP
                ),
                legal_actions[0],
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

            for depth in range(1, self.depth + 1):
                try:
                    completed_action, _ = self._search_root(
                        gameState,
                        depth,
                        preferred_action,
                    )
                except _SearchTimeout:
                    break

                best_action = completed_action
                preferred_action = completed_action

            return best_action
        finally:
            self._search_time_used += time.perf_counter() - start_time
            self._turn_count += 1
            self._deadline = None
