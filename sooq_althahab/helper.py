from rest_framework import status
from rest_framework.request import Request

from account.message import MESSAGES
from sooq_althahab.enums.account import UserRoleBusinessChoices
from sooq_althahab.enums.account import UserRoleChoices
from sooq_althahab.utils import generic_response

from .constants import ROLE_AND_PERMISSIONS


class PermissionManager:
    """
    Class to manage and check permissions for users based on their roles.

    Attributes:
        required_permissions (list): A list of dictionaries representing the required permissions
        for a user to access a particular functionality.
    """

    def __init__(self, required_permissions):
        self.required_permissions = required_permissions

    def check_permission(self, user_permissions, permission) -> bool:
        for key, value in permission.items():
            perms = user_permissions.get(key)
            if not perms or not set(value).issubset(perms):
                return False
        return True

    def has_permission(self, user_permissions):
        for permission in self.required_permissions:
            # Check if user has all permissions from dict.
            if self.check_permission(user_permissions, permission):
                return True
        # If user does not have any permissions then return False.
        return False

    def __call__(self, function):
        """
        Check permissions before executing the function.
        """

        def wrapper(*args, **kwargs):
            # Loop through the function arguments.
            all_roles = {
                **UserRoleChoices.__members__,
                **UserRoleBusinessChoices.__members__,
            }
            for arg in args:
                # Check if the argument is a Request object.
                if isinstance(arg, Request):
                    # Retrieve the user's role from the request.
                    user_role = arg.auth.get("role", None)
                    if user_role not in all_roles:
                        break

                    # Get the user's permissions based on their role.
                    user_permissions = ROLE_AND_PERMISSIONS.get(
                        all_roles[user_role].label
                    )
                    if user_permissions and self.has_permission(user_permissions):
                        return function(*args, **kwargs)
            # If the user does not have the necessary permissions or
            # function argument does not have request object then throw error.
            return generic_response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_message=MESSAGES["unauthorized"],
            )

        return wrapper
