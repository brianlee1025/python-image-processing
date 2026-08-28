import asyncio
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Annotated, Any

import typer

from .settings import settings

app = typer.Typer()


def syncify(f: Callable[..., Any]) -> Callable[..., Any]:
    """This simple decorator converts an async function into a sync function,
    allowing it to work with Typer.
    """

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))

    return wrapper


@app.command(help="Install testing data for local development.")
@syncify
async def test_data() -> None:
    from . import __version__
    from .services.db import get_session, test_data

    typer.echo(f"{settings.project_name} - {__version__}")

    async with get_session() as session:
        await test_data(session)

    typer.echo("Development data installed successfully.")


@app.command(help="Consume share card requests from Kafka and reply with rendered cards.")
def render_worker() -> None:
    from .worker import run_worker

    run_worker()


@app.command(help="Render a demo card to a file, e.g. for checking a theme or a font change.")
def sample_card(
    kind: Annotated[str, typer.Option(help="USER, SQUAD, EVENT or POST.")] = "USER",
    layout: Annotated[str, typer.Option(help="POSTER (1080x1350), STORY (1080x1920) or CARD (1200x630).")] = "POSTER",
    theme: Annotated[str | None, typer.Option(help="midnight, turf, sunset, court or ocean.")] = None,
    out: Annotated[Path, typer.Option(help="Where to write the image.")] = Path("sample-card.png"),
) -> None:
    import base64

    from .samples import sample_request
    from .services.share_cards import render_now

    result = render_now(sample_request(kind=kind.upper(), layout=layout.upper(), theme=theme))  # type: ignore[arg-type]
    if result.status != "COMPLETED" or not result.image_base64:
        message = result.error.message if result.error else "unknown error"
        typer.echo(f"Render failed: {message}", err=True)
        raise typer.Exit(code=1)

    out.write_bytes(base64.b64decode(result.image_base64))
    typer.echo(f"Wrote {out} ({result.width}x{result.height}, {result.byte_size} bytes, {result.render_ms}ms)")


@app.command(help=f"Display the current installed version of {settings.project_name}.")
def version() -> None:
    from . import __version__

    typer.echo(f"{settings.project_name} - {__version__}")


@app.command(help="Display a friendly greeting.")
def hello() -> None:
    typer.echo(f"Hello from {settings.project_name}!")


if __name__ == "__main__":
    app()
