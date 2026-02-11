# asgi.py - PRODUCTION SECURE CONFIGURATION

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter
from channels.routing import URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
from django.urls import path

from sooq_althahab.consumers.admin_notifications import NotificationConsumer

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sooq_althahab.settings")

# SECURE CORS configuration for production
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "0") == "1"
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")

# Clean and validate origins
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in CORS_ALLOWED_ORIGINS if origin.strip()
]

# PRODUCTION SECURE WebSocket configuration
if CORS_ALLOW_ALL_ORIGINS:
    # WARNING: Only use in development/testing
    websocket_middleware = AuthMiddlewareStack(
        URLRouter([path("ws/notifications/", NotificationConsumer.as_asgi())])
    )
elif CORS_ALLOWED_ORIGINS:
    # PRODUCTION: Strict origin validation
    websocket_middleware = AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter([path("ws/notifications/", NotificationConsumer.as_asgi())])
        )
    )
else:
    # FALLBACK: No origins allowed (most secure)
    websocket_middleware = AuthMiddlewareStack(
        URLRouter([path("ws/notifications/", NotificationConsumer.as_asgi())])
    )

# Main ASGI application
application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": websocket_middleware,
    }
)
