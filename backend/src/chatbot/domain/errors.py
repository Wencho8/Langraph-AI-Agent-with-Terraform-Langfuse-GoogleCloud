class ChatError(Exception):
    code = "internal_error"
    message = "The request could not be completed."


class Unauthorized(ChatError):
    code = "unauthenticated"
    message = "Please sign in again."


class InvalidCredentials(ChatError):
    code = "invalid_credentials"
    message = "Invalid username or password."


class UsernameTaken(ChatError):
    code = "username_taken"
    message = "That username is already taken."


class Forbidden(ChatError):
    code = "forbidden"
    message = "The request origin or CSRF token is invalid."


class AuthRateLimited(ChatError):
    code = "auth_rate_limited"
    message = "Too many authentication attempts. Try again in a minute."


class AuthBusy(ChatError):
    code = "auth_busy"
    message = "Authentication is busy. Try again shortly."


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


class InvalidToolCall(ChatError):
    code = "invalid_tool_call"
    message = "The model requested an unavailable tool or invalid arguments."


class ToolTimedOut(ChatError):
    code = "tool_timeout"
    message = "A tool exceeded its time limit."


class ToolFailed(ChatError):
    code = "tool_failed"
    message = "A tool could not complete its operation."


class ProviderAuthentication(ChatError):
    code = "provider_authentication"
    message = "The model provider rejected the credentials or model access."


class ProviderRateLimited(ChatError):
    code = "provider_rate_limited"
    message = "The model provider rejected the request due to its rate or quota limits."


class ProviderUnavailable(ChatError):
    code = "provider_unavailable"
    message = "The model provider is unavailable."


class ProviderRejected(ChatError):
    code = "provider_rejected"
    message = "The model provider rejected the request or selected model."


class ContextLimit(ChatError):
    code = "context_limit"
    message = "The full conversation exceeds the selected model's context limit."


class OutputLimit(ChatError):
    code = "output_limit"
    message = "The model reached its configured output limit before completing."


class InvalidModelResponse(ChatError):
    code = "invalid_model_response"
    message = "The model did not produce a complete, valid response."


class ProviderRefused(ChatError):
    code = "provider_refused"
    message = "The model provider declined this request."
