import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import close_old_connections
from rest_framework_simplejwt.exceptions import TokenError

from sooq_althahab.enums.account import UserRoleChoices

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Close any stale database connections before starting
        close_old_connections()

        # Retrieve token from the query string
        token = self.scope["query_string"]
        token = parse_qs(token.decode()).get("token", [None])[0]

        logger.debug("Received connection request with token: %s", token)

        if not token:
            logger.warning("No token provided, closing connection.")
            await self.close(code=4000)
            return

        try:
            from rest_framework_simplejwt.tokens import AccessToken

            # Here, validate the token and retrieve user info
            decoded_token = AccessToken(token)
            logger.debug("Token successfully decoded: %s", decoded_token.payload)

            # Get the organization code from the token payload
            self.organization_code = decoded_token.payload.get("organization_code")
            if not self.organization_code:
                logger.warning("Organization code not found in the token payload.")
                await self.close(code=4000)
                return

            # Get the user role from the token payload and check user is ADMIN, TAQABETH_ENFORCER, JEWELLERY_INSPECTOR, or JEWELLERY_BUYER
            self.role = decoded_token.payload.get("role")
            self.user_id = decoded_token.payload.get("user_id")

            if self.role not in UserRoleChoices:
                group_name = f"notifications_{self.user_id}"
            else:
                group_name = f"notifications_{self.organization_code}"

            logger.debug("Organization code: %s", self.organization_code)

        except TokenError as e:
            logger.warning("Invalid or expired token: %s", str(e))
            await self.close(code=4000)
            return

        except Exception as e:
            logger.error("Error decoding token or fetching organization code: %s", e)
            await self.close(code=4000)
            return

        # Construct the room group name based on the organization code
        self.room_group_name = group_name
        logger.debug("Joining group: %s", self.room_group_name)

        # Join the group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info("User connected and accepted.")

        try:
            count = await self.get_notification_count()
            await self.notification_count(
                {"type": "notification_count", "count": count}
            )
        finally:
            # Always close connections after database operations
            close_old_connections()

    async def disconnect(self, close_code):
        # Close database connections on disconnect
        close_old_connections()

        # Ensure room_group_name is defined before attempting to leave the group
        if hasattr(self, "room_group_name"):
            logger.debug("Leaving group: %s", self.room_group_name)
            # Leave the group if room_group_name exists
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )
        else:
            logger.warning("No room_group_name defined, skipping group discard.")

        # Handle connection closing or clean-up if necessary
        logger.info(f"Connection closed with code {close_code}")

    async def receive(self, text_data):
        # Handle received messages (you might not need this for notifications)
        logger.debug("Received message: %s", text_data)

    async def notification_message(self, event):
        # Send message to WebSocket
        message = event["message"]
        data = event["data"]
        logger.debug("Sending notification data: %s", data)
        logger.debug("Sending notification message: %s", message)
        await self.send(text_data=json.dumps({"message": message, "data": data}))

    async def notification_count(self, event):
        # Send message to WebSocket
        count = event["count"]
        logger.debug("Sending notification count: %s", count)
        await self.send(text_data=json.dumps({"count": count}))

    @database_sync_to_async
    def get_notification_count(self):
        from sooq_althahab_admin.models import Notification

        try:
            # Close old connections before query
            close_old_connections()
            count = Notification.objects.filter(
                user_id=self.user_id, is_read=False
            ).count()
            # Close connections after query
            close_old_connections()
            return count
        except Exception as e:
            logger.error(f"Error getting notification count: {e}")
            close_old_connections()
            return 0
