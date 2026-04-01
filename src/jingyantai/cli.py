import typer

app = typer.Typer(name="jingyantai", no_args_is_help=True)


@app.callback()
def main() -> None:
    """竞研台 CLI."""
