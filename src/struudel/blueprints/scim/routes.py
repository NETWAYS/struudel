import logging
from typing import Any

from flask import request
from sqlalchemy.exc import IntegrityError
from werkzeug.wrappers import Response

from struudel.blueprints.scim import bp
from struudel.blueprints.scim.auth import require_scim_token
from struudel.blueprints.scim.responses import scim_error, scim_response
from struudel.database import SessionLocal
from struudel.services import group as group_service
from struudel.services import scim as scim_service
from struudel.services import user as user_service
from struudel.services.scim import SCIM_CONTENT_TYPE, ScimError

log = logging.getLogger(__name__)


@bp.errorhandler(ScimError)
def _handle_scim_error(e: ScimError) -> Response:
    if e.status == 400:
        log.warning(
            "SCIM 400 %s %s detail=%r body=%r",
            request.method,
            request.path,
            e.detail,
            request.get_data(as_text=True)[:2000],
        )
    return scim_error(e.status, e.detail, e.scim_type)


@bp.errorhandler(IntegrityError)
def _handle_integrity_error(e: IntegrityError) -> Response:
    diag = getattr(getattr(e, "orig", None), "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    detail = getattr(diag, "message_detail", None)
    log.warning(
        "SCIM 409 %s %s constraint=%r detail=%r body=%r",
        request.method,
        request.path,
        constraint,
        detail,
        request.get_data(as_text=True)[:2000],
    )
    return scim_error(409, "Conflict on unique attribute", "uniqueness")


def _require_json_body() -> dict[str, Any]:
    payload = request.get_json(force=True, silent=True)
    if not isinstance(payload, dict):
        raise ScimError(400, "Request body must be a JSON object", "invalidSyntax")
    return payload


def _parse_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as e:
        raise ScimError(404, "Resource not found", None) from e


# --- Discovery endpoints ---------------------------------------------------


@bp.route("/ServiceProviderConfig", methods=["GET"])
@require_scim_token
def service_provider_config() -> Response:
    return scim_response(scim_service.service_provider_config())


@bp.route("/ResourceTypes", methods=["GET"])
@require_scim_token
def resource_types() -> Response:
    types = scim_service.resource_types()
    return scim_response(scim_service.list_response(types, total=len(types), start_index=1))


@bp.route("/Schemas", methods=["GET"])
@require_scim_token
def schemas() -> Response:
    items = scim_service.schemas()
    return scim_response(scim_service.list_response(items, total=len(items), start_index=1))


# --- Users -----------------------------------------------------------------


@bp.route("/Users", methods=["GET"])
@require_scim_token
def users_list() -> Response:
    filter_pair = scim_service.parse_eq_filter(request.args.get("filter"))
    start_index, count = scim_service.parse_pagination(
        request.args.get("startIndex"), request.args.get("count")
    )

    with SessionLocal() as db:
        users, total = user_service.list_users(
            db,
            filter_attr=filter_pair[0] if filter_pair else None,
            filter_value=filter_pair[1] if filter_pair else None,
            start_index=start_index,
            count=count,
        )
        resources = [scim_service.user_to_scim(u) for u in users]

    return scim_response(
        scim_service.list_response(resources, total=total, start_index=start_index)
    )


@bp.route("/Users", methods=["POST"])
@require_scim_token
def users_create() -> Response:
    payload = _require_json_body()
    fields = scim_service.parse_user_payload(payload)
    external_id = fields["external_id"] or fields["preferred_username"]

    with SessionLocal() as db:
        existing = user_service.get_user_by_external_id(db, external_id=external_id)
        if existing is not None:
            user = user_service.update_user(
                db,
                user_id=existing.id,
                preferred_username=fields["preferred_username"],
                name=fields["name"],
                given_name=fields["given_name"],
                family_name=fields["family_name"],
                email=fields["email"],
                active=fields["active"],
                external_id=external_id,
            )
            assert user is not None
            log.info(
                "SCIM POST /Users adopted existing user id=%s external_id=%s",
                user.id,
                external_id,
            )
            status = 200
        else:
            user = user_service.create_user(
                db,
                external_id=external_id,
                preferred_username=fields["preferred_username"],
                name=fields["name"],
                given_name=fields["given_name"],
                family_name=fields["family_name"],
                email=fields["email"],
                active=fields["active"],
            )
            status = 201
        body = scim_service.user_to_scim(user)

    response = scim_response(body, status)
    response.headers["Location"] = body["meta"]["location"]
    return response


@bp.route("/Users/<user_id>", methods=["GET"])
@require_scim_token
def user_detail(user_id: str) -> Response:
    uid = _parse_id(user_id)
    with SessionLocal() as db:
        user = user_service.get_user_by_id(db, user_id=uid)
        if user is None:
            return scim_error(404, "User not found")
        body = scim_service.user_to_scim(user)
    return scim_response(body)


@bp.route("/Users/<user_id>", methods=["PUT"])
@require_scim_token
def user_replace(user_id: str) -> Response:
    uid = _parse_id(user_id)
    payload = _require_json_body()
    fields = scim_service.parse_user_payload(payload)

    with SessionLocal() as db:
        user = user_service.update_user(
            db,
            user_id=uid,
            preferred_username=fields["preferred_username"],
            name=fields["name"],
            given_name=fields["given_name"],
            family_name=fields["family_name"],
            email=fields["email"],
            active=fields["active"],
            external_id=fields["external_id"],
        )
        if user is None:
            return scim_error(404, "User not found")
        body = scim_service.user_to_scim(user)

    return scim_response(body)


@bp.route("/Users/<user_id>", methods=["PATCH"])
@require_scim_token
def user_patch(user_id: str) -> Response:
    uid = _parse_id(user_id)
    payload = _require_json_body()
    ops = scim_service.parse_patch_ops(payload)
    fields = scim_service.user_patch_to_fields(ops)

    with SessionLocal() as db:
        user = (
            user_service.update_user(db, user_id=uid, **fields)
            if fields
            else user_service.get_user_by_id(db, user_id=uid)
        )
        if user is None:
            return scim_error(404, "User not found")
        body = scim_service.user_to_scim(user)

    return scim_response(body)


@bp.route("/Users/<user_id>", methods=["DELETE"])
@require_scim_token
def user_delete(user_id: str) -> Response:
    uid = _parse_id(user_id)
    with SessionLocal() as db:
        deactivated = user_service.deactivate_user(db, user_id=uid)
    if not deactivated:
        return scim_error(404, "User not found or already inactive")
    return Response(status=204, mimetype=SCIM_CONTENT_TYPE)


# --- Groups ----------------------------------------------------------------


@bp.route("/Groups", methods=["GET"])
@require_scim_token
def groups_list() -> Response:
    filter_pair = scim_service.parse_eq_filter(request.args.get("filter"))
    start_index, count = scim_service.parse_pagination(
        request.args.get("startIndex"), request.args.get("count")
    )

    with SessionLocal() as db:
        groups, total = group_service.list_groups(
            db,
            filter_attr=filter_pair[0] if filter_pair else None,
            filter_value=filter_pair[1] if filter_pair else None,
            start_index=start_index,
            count=count,
        )
        resources = [scim_service.group_to_scim(g) for g in groups]

    return scim_response(
        scim_service.list_response(resources, total=total, start_index=start_index)
    )


@bp.route("/Groups", methods=["POST"])
@require_scim_token
def groups_create() -> Response:
    payload = _require_json_body()
    fields = scim_service.parse_group_payload(payload)

    with SessionLocal() as db:
        existing = (
            group_service.get_group_by_external_id(db, external_id=fields["external_id"])
            if fields["external_id"]
            else None
        )
        if existing is not None:
            group = group_service.update_group(
                db,
                group_id=existing.id,
                display_name=fields["display_name"],
                external_id=fields["external_id"],
                member_user_ids=fields["member_user_ids"],
            )
            assert group is not None
            log.info(
                "SCIM POST /Groups adopted existing group id=%s external_id=%s",
                group.id,
                fields["external_id"],
            )
            status = 200
        else:
            group = group_service.create_group(
                db,
                display_name=fields["display_name"],
                external_id=fields["external_id"],
                member_user_ids=fields["member_user_ids"],
            )
            status = 201
        group_service.sync_superusers_from_group(db)
        body = scim_service.group_to_scim(group)

    response = scim_response(body, status)
    response.headers["Location"] = body["meta"]["location"]
    return response


@bp.route("/Groups/<group_id>", methods=["GET"])
@require_scim_token
def group_detail(group_id: str) -> Response:
    gid = _parse_id(group_id)
    with SessionLocal() as db:
        group = group_service.get_group_by_id(db, group_id=gid)
        if group is None:
            return scim_error(404, "Group not found")
        body = scim_service.group_to_scim(group)
    return scim_response(body)


@bp.route("/Groups/<group_id>", methods=["PUT"])
@require_scim_token
def group_replace(group_id: str) -> Response:
    gid = _parse_id(group_id)
    payload = _require_json_body()
    fields = scim_service.parse_group_payload(payload)

    with SessionLocal() as db:
        group = group_service.update_group(
            db,
            group_id=gid,
            display_name=fields["display_name"],
            external_id=fields["external_id"],
            member_user_ids=fields["member_user_ids"],
        )
        if group is None:
            return scim_error(404, "Group not found")
        group_service.sync_superusers_from_group(db)
        body = scim_service.group_to_scim(group)

    return scim_response(body)


@bp.route("/Groups/<group_id>", methods=["PATCH"])
@require_scim_token
def group_patch(group_id: str) -> Response:
    gid = _parse_id(group_id)
    payload = _require_json_body()
    ops = scim_service.parse_patch_ops(payload)
    actions = scim_service.group_patch_to_actions(ops)

    with SessionLocal() as db:
        group = group_service.patch_group(
            db,
            group_id=gid,
            display_name=actions["display_name"],
            external_id=actions["external_id"],
            replace_members=actions["replace_members"],
            add_members=actions["add_members"],
            remove_members=actions["remove_members"],
        )
        if group is None:
            return scim_error(404, "Group not found")
        group_service.sync_superusers_from_group(db)
        body = scim_service.group_to_scim(group)

    return scim_response(body)


@bp.route("/Groups/<group_id>", methods=["DELETE"])
@require_scim_token
def group_delete(group_id: str) -> Response:
    gid = _parse_id(group_id)
    with SessionLocal() as db:
        removed = group_service.delete_group(db, group_id=gid)
        if not removed:
            return scim_error(404, "Group not found")
        group_service.sync_superusers_from_group(db)
    return Response(status=204, mimetype=SCIM_CONTENT_TYPE)
