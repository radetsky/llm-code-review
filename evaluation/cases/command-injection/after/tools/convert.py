import subprocess


def convert(src: str, dst: str) -> None:
    subprocess.run(["convert", src, dst], check=True)


def thumbnail(filename: str, size: str) -> None:
    subprocess.run(
        f"convert {filename} -resize {size} thumb.png", shell=True, check=True
    )
