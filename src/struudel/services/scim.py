import re
from typing import Any

from flask import url_for

from struudel.models.group import Group
from struudel.models.user import User

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

SCIM_CONTENT_TYPE = "application/scim+json"

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

_FILTER_PATTERN = re.compile(r'^\s*(\w+)\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE)
_REMOVE_MEMBER_PATH = re.compile(r'^members\[\s*value\s+eq\s+"([^"]+)"\s*\]\s*$', re.IGNORECASE)


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type


def error_response(status: int, detail: str, scim_type: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemas": [ERROR_SCHEMA],
        "status": str(status),
        "detail": detail,
    }
    if scim_type:
        body["scimType"] = scim_type
    return body


def parse_eq_filter(filter_expr: str | None) -> tuple[str, str] | None:
    if filter_expr is None or not filter_expr.strip():
        return None
    match = _FILTER_PATTERN.match(filter_expr)
    if not match:
        raise ScimError(400, f"Unsupported filter: {filter_expr!r}", "invalidFilter")
    return match.group(1), match.group(2)


def parse_pagination(start_index_raw: str | None, count_raw: str | None) -> tuple[int, int]:
    try:
        start_index = int(start_index_raw) if start_index_raw else 1
    except ValueError as e:
        raise ScimError(400, "startIndex must be an integer", "invalidValue") from e
    try:
        count = int(count_raw) if count_raw else DEFAULT_PAGE_SIZE
    except ValueError as e:
        raise ScimError(400, "count must be an integer", "invalidValue") from e

    if start_index < 1:
        start_index = 1
    if count < 0:
        count = 0
    if count > MAX_PAGE_SIZE:
        count = MAX_PAGE_SIZE
    return start_index, count


def user_to_scim(user: User) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "schemas": [USER_SCHEMA],
        "id": str(user.id),
        "externalId": user.external_id,
        "userName": user.preferred_username,
        "name": {
            "formatted": user.name,
            "givenName": user.given_name,
            "familyName": user.family_name,
        },
        "emails": [{"value": user.email, "primary": True}],
        "active": user.is_active,
        "meta": {
            "resourceType": "User",
            "created": _isoformat(user.created_at),
            "lastModified": _isoformat(user.updated_at),
            "location": url_for("scim.user_detail", user_id=user.id, _external=True),
        },
    }
    return resource


def group_to_scim(group: Group) -> dict[str, Any]:
    members = [
        {
            "value": str(u.id),
            "type": "User",
            "$ref": url_for("scim.user_detail", user_id=u.id, _external=True),
            "display": u.name or u.preferred_username,
        }
        for u in group.users
    ]
    return {
        "schemas": [GROUP_SCHEMA],
        "id": str(group.id),
        "externalId": group.external_id,
        "displayName": group.name,
        "members": members,
        "meta": {
            "resourceType": "Group",
            "created": _isoformat(group.created_at),
            "lastModified": _isoformat(group.updated_at),
            "location": url_for("scim.group_detail", group_id=group.id, _external=True),
        },
    }


def list_response(
    resources: list[dict[str, Any]], *, total: int, start_index: int
) -> dict[str, Any]:
    return {
        "schemas": [LIST_RESPONSE_SCHEMA],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def parse_user_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ScimError(400, "Request body must be a JSON object", "invalidSyntax")

    username = payload.get("userName")
    if not username:
        raise ScimError(400, "userName is required", "invalidValue")

    emails = payload.get("emails") or []
    email = _primary_email(emails)
    if not email:
        raise ScimError(400, "At least one email is required", "invalidValue")

    name_obj = payload.get("name") or {}
    given = name_obj.get("givenName")
    family = name_obj.get("familyName")
    formatted = name_obj.get("formatted") or _join_name(given, family) or username

    external_id = payload.get("externalId")
    active = payload.get("active", True)
    if not isinstance(active, bool):
        raise ScimError(400, "active must be boolean", "invalidValue")

    return {
        "preferred_username": username,
        "name": formatted,
        "given_name": given,
        "family_name": family,
        "email": email,
        "external_id": external_id,
        "active": active,
    }


def parse_group_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ScimError(400, "Request body must be a JSON object", "invalidSyntax")

    display_name = payload.get("displayName")
    if not display_name:
        raise ScimError(400, "displayName is required", "invalidValue")

    external_id = payload.get("externalId")
    members = payload.get("members") or []
    member_ids = _parse_member_ids(members)

    return {
        "display_name": display_name,
        "external_id": external_id,
        "member_user_ids": member_ids,
    }


def parse_patch_ops(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ScimError(400, "Request body must be a JSON object", "invalidSyntax")
    schemas = payload.get("schemas") or []
    if PATCH_OP_SCHEMA not in schemas:
        raise ScimError(400, "Missing PatchOp schema", "invalidSyntax")

    ops = payload.get("Operations")
    if not isinstance(ops, list):
        raise ScimError(400, "Operations must be a list", "invalidSyntax")

    parsed = []
    for op in ops:
        if not isinstance(op, dict):
            raise ScimError(400, "Each operation must be an object", "invalidSyntax")
        op_name = (op.get("op") or "").lower()
        if op_name not in {"add", "remove", "replace"}:
            raise ScimError(400, f"Unsupported op: {op_name!r}", "invalidSyntax")
        parsed.append({"op": op_name, "path": op.get("path"), "value": op.get("value")})
    return parsed


def user_patch_to_fields(ops: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for op in ops:
        op_name = op["op"]
        path = op["path"]
        value = op["value"]

        if op_name == "remove":
            raise ScimError(400, "remove on User attributes not supported", "invalidSyntax")

        if path is None:
            if not isinstance(value, dict):
                raise ScimError(
                    400, "value must be an object when path is omitted", "invalidSyntax"
                )
            fields.update(_user_attributes_from_dict(value))
        else:
            fields.update(_user_attributes_from_dict({path: value}))
    return fields


def group_patch_to_actions(ops: list[dict[str, Any]]) -> dict[str, Any]:
    actions: dict[str, Any] = {
        "display_name": None,
        "external_id": None,
        "replace_members": None,
        "add_members": [],
        "remove_members": [],
    }

    for op in ops:
        op_name = op["op"]
        path = op["path"]
        value = op["value"]

        if op_name == "replace":
            if path is None:
                if not isinstance(value, dict):
                    raise ScimError(400, "value must be object when path omitted", "invalidSyntax")
                for k, v in value.items():
                    _apply_group_replace(actions, k, v)
            else:
                _apply_group_replace(actions, path, value)

        elif op_name == "add":
            if (path or "").lower() != "members":
                raise ScimError(400, "add only supported on 'members'", "invalidSyntax")
            actions["add_members"].extend(_parse_member_ids(value or []))

        elif op_name == "remove":
            path_str = path or ""
            match = _REMOVE_MEMBER_PATH.match(path_str)
            if match:
                try:
                    actions["remove_members"].append(int(match.group(1)))
                except ValueError as e:
                    raise ScimError(400, "member value must be numeric id", "invalidValue") from e
            elif path_str.lower() == "members":
                if value in (None, []):
                    actions["replace_members"] = []
                elif isinstance(value, list):
                    actions["remove_members"].extend(_parse_member_ids(value))
                else:
                    raise ScimError(400, "remove members value must be list", "invalidValue")
            else:
                raise ScimError(
                    400,
                    'remove only supported on members (with or without value-eq filter)',
                    "invalidSyntax",
                )

    return actions


def _apply_group_replace(actions: dict[str, Any], path: str, value: Any) -> None:
    key = path.lower()
    if key == "displayname":
        actions["display_name"] = value
    elif key == "externalid":
        actions["external_id"] = value
    elif key == "members":
        actions["replace_members"] = _parse_member_ids(value or [])
    else:
        raise ScimError(400, f"Unsupported path: {path!r}", "invalidPath")


def _user_attributes_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_key, value in data.items():
        key = raw_key.lower() if isinstance(raw_key, str) else ""
        if key == "username":
            out["preferred_username"] = value
        elif key == "externalid":
            out["external_id"] = value
        elif key == "active":
            if not isinstance(value, bool):
                raise ScimError(400, "active must be boolean", "invalidValue")
            out["active"] = value
        elif key == "emails":
            email = _primary_email(value or [])
            if email:
                out["email"] = email
        elif key == "name":
            if not isinstance(value, dict):
                raise ScimError(400, "name must be object", "invalidValue")
            given = value.get("givenName")
            family = value.get("familyName")
            formatted = value.get("formatted") or _join_name(given, family)
            if given is not None:
                out["given_name"] = given
            if family is not None:
                out["family_name"] = family
            if formatted is not None:
                out["name"] = formatted
        elif key in {"name.givenname", "name.familyname", "name.formatted"}:
            subkey = key.split(".")[1]
            if subkey == "givenname":
                out["given_name"] = value
            elif subkey == "familyname":
                out["family_name"] = value
            else:
                out["name"] = value
        else:
            raise ScimError(400, f"Unsupported path: {raw_key!r}", "invalidPath")
    return out


def _primary_email(emails: list[Any]) -> str | None:
    if not isinstance(emails, list) or not emails:
        return None
    for entry in emails:
        if isinstance(entry, dict) and entry.get("primary") and entry.get("value"):
            return entry["value"]
    for entry in emails:
        if isinstance(entry, dict) and entry.get("value"):
            return entry["value"]
    return None


def _parse_member_ids(members: Any) -> list[int]:
    if not isinstance(members, list):
        raise ScimError(400, "members must be a list", "invalidValue")
    ids: list[int] = []
    for entry in members:
        if not isinstance(entry, dict) or "value" not in entry:
            raise ScimError(400, "Each member requires 'value'", "invalidValue")
        try:
            ids.append(int(entry["value"]))
        except (TypeError, ValueError) as e:
            raise ScimError(400, "member value must be numeric id", "invalidValue") from e
    return ids


def _join_name(given: str | None, family: str | None) -> str | None:
    parts = [p for p in (given, family) if p]
    return " ".join(parts) if parts else None


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def service_provider_config() -> dict[str, Any]:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://datatracker.ietf.org/doc/html/rfc7644",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_PAGE_SIZE},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication via HTTP Bearer token",
                "specUri": "https://datatracker.ietf.org/doc/html/rfc6750",
            }
        ],
    }


def resource_types() -> list[dict[str, Any]]:
    return [
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": USER_SCHEMA,
        },
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": GROUP_SCHEMA,
        },
    ]


def schemas() -> list[dict[str, Any]]:
    return [
        {"id": USER_SCHEMA, "name": "User"},
        {"id": GROUP_SCHEMA, "name": "Group"},
    ]
