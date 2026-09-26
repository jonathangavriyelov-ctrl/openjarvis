"""Personal AI OS commands."""

from __future__ import annotations

import click

from openjarvis.personal.gate import MIN_PASSWORD_LENGTH, set_password


@click.group("os", help="Personal AI OS commands.")
def os_group() -> None:
    """Desk commands that run on this machine."""


@os_group.command("reset-password")
@click.option(
    "--password",
    default=None,
    help="New password. You are prompted when this is omitted.",
)
def reset_password(password: str | None) -> None:
    """Replace the desk password and close open sessions."""
    chosen = password
    if chosen is None:
        chosen = click.prompt(
            "New password",
            hide_input=True,
            confirmation_prompt=True,
        )
    try:
        set_password(chosen)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        "Password updated. Open the desk and sign in. "
        f"Use at least {MIN_PASSWORD_LENGTH} characters. "
        "Old sessions are closed."
    )
