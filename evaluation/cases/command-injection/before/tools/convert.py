import subprocess


def convert(src: str, dst: str) -> None:
    subprocess.run(["convert", src, dst], check=True)
