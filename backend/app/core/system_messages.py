"""Translated system messages for guards and action runners.

All messages that guards and confirmation handlers send directly to the user
(no AI involved) live here, keyed by message ID and base language code.
Falls back to Spanish for any untranslated language.
"""
from __future__ import annotations

_MSGS: dict[str, dict[str, str]] = {
    # ── pending_action_runner — generic ───────────────────────────────────
    "action_unknown_type": {
        "es": "Tipo de acción desconocido: {action_type}",
        "en": "Unknown action type: {action_type}",
        "ja": "不明なアクションタイプ: {action_type}",
    },
    "action_executed": {
        "es": "Acción ejecutada: {summary}",
        "en": "Action executed: {summary}",
        "ja": "アクション実行済み: {summary}",
    },
    "action_pre_command": {
        "es": "\nPreparación: {cmd}",
        "en": "\nPreparation: {cmd}",
        "ja": "\n準備: {cmd}",
    },
    "action_pre_stdout": {
        "es": "Salida: {out}",
        "en": "Output: {out}",
        "ja": "出力: {out}",
    },
    "action_command": {
        "es": "\nComando: {cmd}",
        "en": "\nCommand: {cmd}",
        "ja": "\nコマンド: {cmd}",
    },
    "action_stdout": {
        "es": "Salida:\n{stdout}",
        "en": "Output:\n{stdout}",
        "ja": "出力:\n{stdout}",
    },
    "no_output": {
        "es": "(sin salida)",
        "en": "(no output)",
        "ja": "(出力なし)",
    },
    "unknown_error": {
        "es": "Error desconocido",
        "en": "Unknown error",
        "ja": "不明なエラー",
    },
    "action_exec_failed": {
        "es": "No he podido ejecutar la acción pendiente {action_id}.\n\nError:\n{error}",
        "en": "Could not execute pending action {action_id}.\n\nError:\n{error}",
        "ja": "保留中のアクション {action_id} を実行できませんでした。\n\nエラー:\n{error}",
    },
    "action_exec_exception": {
        "es": "Falló la ejecución de la acción pendiente {action_id}: {exc}",
        "en": "Pending action {action_id} failed: {exc}",
        "ja": "保留中のアクション {action_id} の実行に失敗しました: {exc}",
    },
    # ── pending_action_runner — system actions ────────────────────────────
    "sys_post_status": {
        "es": "\nEstado posterior: {status}",
        "en": "\nPost-execution status: {status}",
        "ja": "\n実行後の状態: {status}",
    },
    "sys_no_confirm": {
        "es": "El comando terminó sin confirmación de éxito. Estado posterior: {post_status}",
        "en": "Command finished without success confirmation. Post-execution status: {post_status}",
        "ja": "コマンドが成功確認なしに終了しました。実行後の状態: {post_status}",
    },
    "config_updated": {
        "es": "Configuración actualizada.",
        "en": "Configuration updated.",
        "ja": "設定が更新されました。",
    },
    # ── pending_action_runner — file actions ──────────────────────────────
    "file_diff_applied": {
        "es": "Unified diff aplicado: {path}",
        "en": "Unified diff applied: {path}",
        "ja": "Unified diff 適用済み: {path}",
    },
    "file_rollback_applied": {
        "es": "Rollback aplicado: {path}\nRestaurado desde: {backup}",
        "en": "Rollback applied: {path}\nRestored from: {backup}",
        "ja": "ロールバック適用済み: {path}\n復元元: {backup}",
    },
    "file_patch_applied": {
        "es": "Patch aplicado: {path}",
        "en": "Patch applied: {path}",
        "ja": "パッチ適用済み: {path}",
    },
    "file_created": {
        "es": "Archivo creado: {path}",
        "en": "File created: {path}",
        "ja": "ファイル作成済み: {path}",
    },
    "file_overwritten": {
        "es": "Archivo sobreescrito: {path}",
        "en": "File overwritten: {path}",
        "ja": "ファイル上書き済み: {path}",
    },
    "file_action_executed": {
        "es": "Acción de archivo ejecutada: {path}",
        "en": "File action executed: {path}",
        "ja": "ファイルアクション実行済み: {path}",
    },
    "file_diff_failed": {
        "es": "No he podido aplicar el unified diff: {error}",
        "en": "Could not apply unified diff: {error}",
        "ja": "Unified diff を適用できませんでした: {error}",
    },
    "file_rollback_failed": {
        "es": "No he podido hacer el rollback: {error}",
        "en": "Could not perform rollback: {error}",
        "ja": "ロールバックを実行できませんでした: {error}",
    },
    "file_patch_failed": {
        "es": "No he podido aplicar el patch: {error}",
        "en": "Could not apply patch: {error}",
        "ja": "パッチを適用できませんでした: {error}",
    },
    "file_write_failed": {
        "es": "No he podido escribir el archivo: {error}",
        "en": "Could not write file: {error}",
        "ja": "ファイルを書き込めませんでした: {error}",
    },
    "file_action_exception": {
        "es": "Falló la acción de archivo: {exc}",
        "en": "File action failed: {exc}",
        "ja": "ファイルアクションに失敗しました: {exc}",
    },
    # ── pending_action_runner — sense ─────────────────────────────────────
    "sense_done": {
        "es": "Listo. {summary}.",
        "en": "Done. {summary}.",
        "ja": "完了しました。{summary}。",
    },
    # ── local_flow ────────────────────────────────────────────────────────
    "action_id_exact_needed": {
        "es": (
            "He detectado la acción `{action_id}`, pero la confirmación debe ser exacta.\n\n"
            "Usa: `{phrase}`"
        ),
        "en": (
            "I detected action `{action_id}`, but the confirmation must be exact.\n\n"
            "Use: `{phrase}`"
        ),
        "ja": (
            "アクション `{action_id}` を検出しましたが、確認は正確に入力する必要があります。\n\n"
            "使用: `{phrase}`"
        ),
    },
    "action_not_pending": {
        "es": "La acción `{action_id}` no está pendiente; su estado actual es `{status}`.",
        "en": "Action `{action_id}` is not pending; its current status is `{status}`.",
        "ja": "アクション `{action_id}` は保留中ではありません。現在の状態は `{status}` です。",
    },
    "action_already_executed": {
        "es": " Ya fue ejecutada, no voy a repetirla.",
        "en": " It was already executed, I won't repeat it.",
        "ja": " すでに実行されました。繰り返しません。",
    },
    "action_expired": {
        "es": " Ya expiró. Crea una acción nueva si todavía quieres hacer eso.",
        "en": " It has expired. Create a new action if you still want to do that.",
        "ja": " 期限切れです。まだ実行したい場合は新しいアクションを作成してください。",
    },
    "action_previously_failed": {
        "es": " Falló anteriormente. Crea una acción nueva si quieres reintentarlo.",
        "en": " It failed previously. Create a new action if you want to retry.",
        "ja": " 以前に失敗しました。再試行する場合は新しいアクションを作成してください。",
    },
    "action_not_found": {
        "es": (
            "No encuentro ninguna acción con ID `{action_id}`. "
            "Puede que sea antigua, incorrecta o de otra base de datos."
        ),
        "en": (
            "I can't find any action with ID `{action_id}`. "
            "It may be old, incorrect, or from a different database."
        ),
        "ja": (
            "ID `{action_id}` のアクションが見つかりません。"
            "古いもの、誤ったもの、または別のデータベースのものかもしれません。"
        ),
    },
    "multiple_pending_actions": {
        "es": (
            "Hay varias acciones pendientes, así que no voy a adivinar cuál quieres ejecutar. "
            "Confirma usando la frase exacta de la acción, tipo `confirmo ejecutar act_xxxxxxxx`."
        ),
        "en": (
            "There are multiple pending actions, so I won't guess which one you want to execute. "
            "Confirm using the exact phrase for the action, e.g. `confirmo ejecutar act_xxxxxxxx`."
        ),
        "ja": (
            "複数の保留中アクションがあるため、どれを実行したいか推測しません。"
            "`confirmo ejecutar act_xxxxxxxx` のようにアクションの正確なフレーズで確認してください。"
        ),
    },
    "ambiguous_confirmation": {
        "es": "¿Te refieres a «{summary}»? Usa `{phrase}` para confirmar.",
        "en": "Do you mean «{summary}»? Use `{phrase}` to confirm.",
        "ja": "「{summary}」のことですか？確認するには `{phrase}` を使用してください。",
    },
    # ── budget_guard ──────────────────────────────────────────────────────
    "budget_local_only": {
        "es": (
            "Modo local-only activo. No voy a llamar a Claude. "
            "Puedo ejecutar confirmaciones pendientes y respuestas locales, "
            "pero no interpretar nuevas peticiones con IA."
        ),
        "en": (
            "Local-only mode active. I won't call Claude. "
            "I can execute pending confirmations and local responses, "
            "but not process new AI requests."
        ),
        "ja": (
            "ローカルのみモードが有効です。Claudeを呼び出しません。"
            "保留中の確認とローカル応答は実行できますが、"
            "新しいAIリクエストは処理できません。"
        ),
    },
    "budget_exhausted": {
        "es": (
            "Presupuesto diario de IA agotado. No voy a llamar a Claude ahora. "
            "Puedo seguir resolviendo confirmaciones, acciones pendientes y respuestas locales "
            "que no requieran IA."
        ),
        "en": (
            "Daily AI budget exhausted. I won't call Claude right now. "
            "I can still handle confirmations, pending actions, and local responses "
            "that don't require AI."
        ),
        "ja": (
            "日次AIバジェットが使い果たされました。今はClaudeを呼び出しません。"
            "AIを必要としない確認、保留中アクション、ローカル応答は引き続き処理できます。"
        ),
    },
    # ── user_message_guard ────────────────────────────────────────────────
    "msg_limit_reached": {
        "es": (
            "Has alcanzado tu límite de mensajes de hoy. "
            "Vuelve mañana o contacta con el administrador."
        ),
        "en": (
            "You have reached your daily message limit. "
            "Come back tomorrow or contact the administrator."
        ),
        "ja": (
            "本日のメッセージ上限に達しました。"
            "明日また来るか、管理者にお問い合わせください。"
        ),
    },
}


def t(key: str, lang: str, **kwargs: str) -> str:
    """Return the translated system message for *key* in *lang*.

    Falls back to Spanish if *lang* is not covered.
    *kwargs* are format placeholders inside the template.
    """
    entry = _MSGS.get(key, {})
    template = entry.get(lang) or entry.get("es") or key
    return template.format_map(kwargs)
