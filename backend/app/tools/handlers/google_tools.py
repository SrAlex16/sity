from __future__ import annotations

import datetime

from googleapiclient.discovery import build

from app.actions.confirmation_manager import ConfirmationManager
from app.integrations.google_auth import is_google_connected, load_credentials
from app.tools.registry import ToolContext, tool_handler
from app.tools.types import ToolExecutionResult


def _not_connected(tool_name: str) -> ToolExecutionResult:
    msg = (
        "Google no está conectado. El usuario necesita ejecutar "
        "scripts/google_auth_setup.py una vez para autorizar el acceso."
    )
    return ToolExecutionResult(
        tool_name=tool_name, ok=False, message=msg,
        updated_parameters=[], raw_result={
            "success": False, "message": msg,
            "local_final": True, "text": msg, "local_model": "google-auth-guard",
        },
    )


@tool_handler("gmail_search")
def handle_gmail_search(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    query = str(ctx.tool_input.get("query", ""))
    max_results = min(int(ctx.tool_input.get("max_results", 5)), 10)

    # Default to inbox Principal unless the user already targets another category/label
    _other_categories = ("category:social", "category:promotions",
                         "category:updates", "category:forums",
                         "label:", "in:")
    if not any(c in query.lower() for c in _other_categories):
        base = "category:primary"
        query = f"{base} {query}".strip() if query else base

    creds = load_credentials()
    service = build("gmail", "v1", credentials=creds)

    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results,
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        output = "No se encontraron correos para esa búsqueda."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    summaries = []
    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        snippet = msg.get("snippet", "")[:200]
        summaries.append(
            f"De: {headers.get('From', '?')}\n"
            f"Asunto: {headers.get('Subject', '?')}\n"
            f"Fecha: {headers.get('Date', '?')}\n"
            f"Extracto: {snippet}"
        )

    output = "\n\n---\n\n".join(summaries)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("calendar_list_events")
def handle_calendar_list_events(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    days_ahead = int(ctx.tool_input.get("days_ahead", 7))
    now = datetime.datetime.utcnow().isoformat() + "Z"
    end = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

    creds = load_credentials()
    service = build("calendar", "v3", credentials=creds)

    events_result = service.events().list(
        calendarId="primary", timeMin=now, timeMax=end,
        singleEvents=True, orderBy="startTime", maxResults=20,
    ).execute()

    events = events_result.get("items", [])
    if not events:
        output = f"No hay eventos en los próximos {days_ahead} días."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    lines = []
    for ev in events:
        start = ev["start"].get("dateTime", ev["start"].get("date"))
        lines.append(f"ID: {ev['id']}\n{start} — {ev.get('summary', '(sin título)')}")

    output = "\n".join(lines)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


@tool_handler("calendar_create_event")
def handle_calendar_create_event(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    title = str(ctx.tool_input.get("title", ""))
    start_iso = str(ctx.tool_input.get("start_iso", ""))
    end_iso = str(ctx.tool_input.get("end_iso", ""))
    description = str(ctx.tool_input.get("description", ""))

    if not title or not start_iso or not end_iso:
        msg = "Faltan datos para crear el evento: título, inicio y fin son obligatorios."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    create_payload = {
        "action": "calendar_create_event",
        "title": title,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "description": description,
    }
    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(
        action_type="google", payload=create_payload,
    )
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True, "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "already_existed": True,
            "local_final": True, "text": local_text, "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result=result,
        )

    created = manager.create_pending_action(
        action_type="google",
        risk_level="safe_confirm",
        summary=f"Crear evento en calendario: {title} ({start_iso})",
        payload=create_payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True, "message": local_text,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True, "text": local_text, "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("drive_search")
def handle_drive_search(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    query = str(ctx.tool_input.get("query", "")).strip()
    max_results = min(int(ctx.tool_input.get("max_results", 5)), 10)
    include_shared = bool(ctx.tool_input.get("include_shared", False))

    creds = load_credentials()
    service = build("drive", "v3", credentials=creds)

    if query:
        safe_query = query.replace("'", "\\'")
        drive_filter = f"name contains '{safe_query}' and trashed = false"
    else:
        drive_filter = "trashed = false and 'me' in owners"

    if include_shared:
        drive_filter += " or sharedWithMe = true"

    list_kwargs: dict = {
        "q": drive_filter,
        "pageSize": max_results,
        "fields": "files(id, name, mimeType, modifiedTime, webViewLink, owners)",
    }
    if not query:
        list_kwargs["orderBy"] = "modifiedTime desc"

    results = service.files().list(**list_kwargs).execute()

    files = results.get("files", [])
    if not files:
        output = "No se encontraron archivos para esa búsqueda."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    summaries = [
        f"{f['name']} ({f['mimeType']}) — modificado {f['modifiedTime']}\n{f.get('webViewLink', '(sin enlace)')}"
        for f in files
    ]
    output = "\n\n".join(summaries)
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=output,
        updated_parameters=[], raw_result={"output": output},
    )


def _resolve_event_id_by_title(service: object, event_title: str) -> tuple[str, str]:
    """Return (event_id, error_message). error_message is empty on success."""
    import datetime as dt
    now = dt.datetime.utcnow().isoformat() + "Z"
    end = (dt.datetime.utcnow() + dt.timedelta(days=365)).isoformat() + "Z"
    results = service.events().list(  # type: ignore[union-attr]
        calendarId="primary", timeMin=now, timeMax=end,
        singleEvents=True, orderBy="startTime", maxResults=50,
    ).execute()
    matched = [
        e for e in results.get("items", [])
        if event_title.lower() in e.get("summary", "").lower()
    ]
    if not matched:
        return "", f"No encontré ningún evento con el nombre '{event_title}' en los próximos 365 días."
    if len(matched) > 1:
        names = ", ".join(e.get("summary", "?") for e in matched[:5])
        return "", (
            f"Encontré {len(matched)} eventos que coinciden con '{event_title}': {names}. "
            "Sé más específico o usa el event_id exacto."
        )
    return matched[0]["id"], ""


@tool_handler("calendar_edit_event")
def handle_calendar_edit_event(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    event_id    = str(ctx.tool_input.get("event_id", "")).strip()
    event_title = str(ctx.tool_input.get("event_title", "")).strip()
    title       = ctx.tool_input.get("title")
    start_iso   = ctx.tool_input.get("start_iso")
    end_iso     = ctx.tool_input.get("end_iso")
    description = ctx.tool_input.get("description")
    location    = ctx.tool_input.get("location")

    if not event_id and not event_title:
        msg = "Necesito el event_id o el event_title del evento a editar."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    if not event_id and event_title:
        creds = load_credentials()
        service = build("calendar", "v3", credentials=creds)
        event_id, err = _resolve_event_id_by_title(service, event_title)
        if err:
            return ToolExecutionResult(
                tool_name=ctx.tool_name, ok=False, message=err,
                updated_parameters=[], raw_result={
                    "success": False, "message": err,
                    "local_final": True, "text": err, "local_model": "tool-policy",
                },
            )

    label = event_title or event_id
    payload: dict = {"action": "calendar_edit_event", "event_id": event_id}
    if event_title: payload["event_title"] = event_title
    if title:       payload["title"]       = title
    if start_iso:   payload["start_iso"]   = start_iso
    if end_iso:     payload["end_iso"]     = end_iso
    if description: payload["description"] = description
    if location:    payload["location"]    = location

    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(action_type="google", payload=payload)
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True, "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "already_existed": True,
            "local_final": True, "text": local_text, "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result=result,
        )

    created = manager.create_pending_action(
        action_type="google",
        risk_level="safe_confirm",
        summary=f"Editar evento de calendario: {label}",
        payload=payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True, "message": local_text,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True, "text": local_text, "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("calendar_delete_event")
def handle_calendar_delete_event(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    event_id    = str(ctx.tool_input.get("event_id", "")).strip()
    event_title = str(ctx.tool_input.get("event_title", "")).strip()

    if not event_id and not event_title:
        msg = "Necesito el event_id o el event_title del evento a borrar."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=msg,
            updated_parameters=[], raw_result={
                "success": False, "message": msg,
                "local_final": True, "text": msg, "local_model": "tool-policy",
            },
        )

    if not event_id and event_title:
        creds = load_credentials()
        service = build("calendar", "v3", credentials=creds)
        event_id, err = _resolve_event_id_by_title(service, event_title)
        if err:
            return ToolExecutionResult(
                tool_name=ctx.tool_name, ok=False, message=err,
                updated_parameters=[], raw_result={
                    "success": False, "message": err,
                    "local_final": True, "text": err, "local_model": "tool-policy",
                },
            )

    label = event_title or event_id
    payload: dict = {"action": "calendar_delete_event", "event_id": event_id}
    if event_title: payload["event_title"] = event_title

    manager = ConfirmationManager(ctx.executor.session)
    existing = manager.find_equivalent_pending_action(action_type="google", payload=payload)
    if existing:
        local_text = (
            f"Ya existe una acción pendiente equivalente: {existing.id}\n\n"
            f"Confirma con: `{existing.confirmation_phrase}`"
        )
        result = {
            "success": True, "message": local_text,
            "action_id": existing.id,
            "confirmation_phrase": existing.confirmation_phrase,
            "summary": existing.summary,
            "already_existed": True,
            "local_final": True, "text": local_text, "local_model": "pending-action-manager",
        }
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=local_text,
            updated_parameters=[], raw_result=result,
        )

    created = manager.create_pending_action(
        action_type="google",
        risk_level="safe_confirm",
        summary=f"Borrar evento de calendario: {label}",
        payload=payload,
        trace_id=ctx.trace_id,
    )
    local_text = (
        f"Acción pendiente creada: {created.summary}\n\n"
        f"Confirma con: `{created.confirmation_phrase}`"
    )
    result = {
        "success": True, "message": local_text,
        "action_id": created.id,
        "confirmation_phrase": created.confirmation_phrase,
        "summary": created.summary,
        "local_final": True, "text": local_text, "local_model": "pending-action-manager",
    }
    return ToolExecutionResult(
        tool_name=ctx.tool_name, ok=True, message=local_text,
        updated_parameters=[], raw_result=result,
    )


@tool_handler("drive_list_folder")
def handle_drive_list_folder(ctx: ToolContext) -> ToolExecutionResult:
    if not is_google_connected():
        return _not_connected(ctx.tool_name)

    folder_name = str(ctx.tool_input.get("folder_name", "")).strip()
    folder_id   = str(ctx.tool_input.get("folder_id", "")).strip()
    max_results = min(int(ctx.tool_input.get("max_results", 20)), 50)

    creds = load_credentials()
    service = build("drive", "v3", credentials=creds)

    _ROOT_ALIASES = {"root", "raiz", "raíz", "inicio", "principal", "mi drive", ""}

    _MIME_LABELS: dict[str, str] = {
        "application/vnd.google-apps.folder":      "Carpeta",
        "application/vnd.google-apps.document":    "Doc",
        "application/vnd.google-apps.spreadsheet": "Hoja",
        "application/pdf":                         "PDF",
    }

    def _format_files(files: list, label: str) -> ToolExecutionResult:
        if not files:
            output = "No se encontraron archivos o carpetas."
            return ToolExecutionResult(
                tool_name=ctx.tool_name, ok=True, message=output,
                updated_parameters=[], raw_result={"output": output},
            )
        lines = [
            f"{_MIME_LABELS.get(f['mimeType'], 'Archivo')} — {f['name']}"
            for f in files
        ]
        output = f"Contenido de '{label}' ({len(files)} elementos):\n" + "\n".join(lines)
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=True, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    # Listar Drive raíz cuando no hay carpeta concreta o se pide la raíz
    if not folder_id and folder_name.lower() in _ROOT_ALIASES:
        res = service.files().list(
            q="'root' in parents and trashed = false",
            pageSize=max_results,
            orderBy="folder,modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime)",
        ).execute()
        return _format_files(res.get("files", []), "Mi Drive (raíz)")

    actual_folder_name = folder_name
    if not folder_id and folder_name:
        safe = folder_name.replace("'", "\\'")
        res = service.files().list(
            q=(f"name contains '{safe}' and mimeType = 'application/vnd.google-apps.folder'"
               " and trashed = false"),
            orderBy="modifiedTime desc",
            fields="files(id, name)",
        ).execute()
        folders = res.get("files", [])
        if not folders:
            output = f"No se encontró ninguna carpeta llamada '{folder_name}'."
            return ToolExecutionResult(
                tool_name=ctx.tool_name, ok=True, message=output,
                updated_parameters=[], raw_result={"output": output},
            )
        folder_id = folders[0]["id"]
        actual_folder_name = folders[0]["name"]

    if not folder_id:
        output = "Necesito el nombre o ID de la carpeta, o deja folder_name vacío para ver el Drive raíz."
        return ToolExecutionResult(
            tool_name=ctx.tool_name, ok=False, message=output,
            updated_parameters=[], raw_result={"output": output},
        )

    res = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        pageSize=max_results,
        orderBy="folder,modifiedTime desc",
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    return _format_files(res.get("files", []), actual_folder_name or folder_id)
