import logging
from urllib.parse import parse_qs

from channels.auth import BaseMiddleware
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class JwtAuthMiddleware(BaseMiddleware):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def decode_token(self, token):
        try:
            from rest_framework_simplejwt.tokens import AccessToken

            access_token = AccessToken(token)
            return access_token
        except Exception:
            raise AuthenticationFailed("Invalid token")

    async def connect(self, scope, receive, send):
        token = self.get_token_from_headers(scope)

        if not token:
            await send({"type": "websocket.close", "code": 4000})
            return

        try:
            access_token = self.decode_token(token)
            scope["user"] = access_token.user  # Add the user object to the scope
        except AuthenticationFailed:
            await send({"type": "websocket.close", "code": 4000})
            return

        await super().connect(scope, receive, send)

    def get_token_from_headers(self, scope):
        """Get token from the WebSocket query string."""
        try:
            logger.info("Extracting query string from scope...")
            query_string = scope.get("query_string", b"")

            if not query_string:
                logger.info("No query string found in scope.")
                return None

            logger.info(f"Raw query string: {query_string}")

            # Parse the query string using parse_qs
            parsed_query = parse_qs(query_string.decode())
            logger.info(f"Parsed query string: {parsed_query}")

            token = parsed_query.get("token", [None])[0]
            if token:
                logger.info("Token successfully retrieved from query string.")
            else:
                logger.info("Token not found in parsed query string.")

            return token
        except Exception as e:
            logger.error(f"Exception occurred while retrieving token from headers. {e}")
            return None
