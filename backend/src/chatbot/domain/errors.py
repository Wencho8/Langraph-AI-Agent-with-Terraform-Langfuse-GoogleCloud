class ChatError(Exception):
    code = "internal_error"
    message = "The request could not be completed."


class UnknownUser(ChatError):
    code = "unknown_user"
    message = "Select a known local user using X-Dev-User-Id."


class SessionBusy(ChatError):
    code = "session_busy"
    message = "This conversation already has an active turn."


class RateLimited(ChatError):
    code = "rate_limited"
    message = "Too many messages. Try again later."


class Saturated(ChatError):
    code = "runtime_saturated"
    message = "The backend has reached its active-turn limit."


class Unavailable(ChatError):
    code = "dependency_unavailable"
    message = "A required dependency is unavailable."


class TurnTimedOut(ChatError):
    code = "turn_timeout"
    message = "The turn exceeded its time limit."


class ModelTimedOut(ChatError):
    code = "model_timeout"
    message = "The model exceeded its time limit."


class ExecutionLimit(ChatError):
    code = "execution_limit"
    message = "The agent exceeded its execution limit."
