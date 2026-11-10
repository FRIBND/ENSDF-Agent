"""
ens2pdf.py — Convert ENSDF files to PDF using the McMaster-MSU Java NDS tool.

HOW TO USE:
  1. Edit the CONFIG section below (ELEMENT, MASS, FILES).
  2. Click the Run Python File button in VS Code.  Done.

OUTPUT:
  • Java NDS writes ALL its output files to OUTPUT_DIR (the staging directory).
    Nothing in that folder is touched or deleted by this script.
  • The generated PDF(s) are moved to the element's pdf/ folder.
"""

import glob
import os
import shutil
import subprocess
import time
from pathlib import Path


# =============================================================================
# CONFIG — edit these three lines, then run
# =============================================================================

ELEMENT = "Cl"   # Element symbol, e.g. "Cl", "S", "Ar", "Si"
MASS    = 35     # Mass number, e.g. 34, 35, 36, 60

# FILES: None  → convert ALL .ens files for the element
#        list  → convert only the named datasets (without .ens extension)
# Example: FILES = ["Cl35_34s_p_g", "Cl35_adopted"]
FILES: list[str] | None = None

# =============================================================================
# PATHS — adjust only if your folder layout is different
# =============================================================================

ENSDF_ROOT = str(Path.cwd())
OUTPUT_DIR = str(Path.cwd())
JAR_GLOB = os.environ.get("ENSDF_NDS_JAR", "**/McMaster_MSU_JAVA_NDS_v*.jar")

# =============================================================================
# SCRIPT — no need to edit below this line
# =============================================================================


def find_jar():
    matches = sorted(glob.glob(JAR_GLOB))
    if not matches:
        raise FileNotFoundError(f"No JAR found matching: {JAR_GLOB}")
    return matches[-1]   # pick the latest version


def ens_files_to_convert():
    """Return list of absolute .ens paths based on the CONFIG above."""
    new_dir = Path(ENSDF_ROOT) / f"A{MASS}" / f"{ELEMENT}{MASS}" / "new"
    if not new_dir.exists():
        raise FileNotFoundError(f"new/ folder not found: {new_dir}")

    if FILES is None:
        paths = sorted(new_dir.glob("*.ens"))
    else:
        paths = []
        for name in FILES:
            p = new_dir / f"{name}.ens"
            if not p.exists():
                print(f"  WARNING: {p} not found — skipped")
            else:
                paths.append(p)
    return paths


def pdf_dest_dir():
    """Return (and create if needed) the element's pdf/ folder."""
    d = Path(ENSDF_ROOT) / f"A{MASS}" / f"{ELEMENT}{MASS}" / "pdf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_java(ens_path: Path, jar: str, out_dir: Path) -> Path | None:
    """Step 1 worker: run Java NDS on one .ens file.
    Returns the generated PDF path, or None on failure.
    Does NOT move the file — all moves happen in Step 2 after every
    conversion is finished."""
    pdf_name = ens_path.stem + ".pdf"
    original_cwd = os.getcwd()
    os.chdir(out_dir)
    try:
        subprocess.run(
            ["java", "-jar", jar, str(ens_path.resolve()), pdf_name],
            check=True, timeout=300,
        )
        generated = out_dir / pdf_name
        if generated.exists():
            print(f"  converted  {ens_path.name}")
            return generated
        else:
            print(f"  WARN  PDF not produced for {ens_path.name}")
            return None
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT  {ens_path.name}")
        return None
    except subprocess.CalledProcessError as e:
        print(f"  ERROR  {ens_path.name}: Java exited with code {e.returncode}")
        return None
    finally:
        os.chdir(original_cwd)


def move_all_pdfs(generated: list, dest_dir: Path, max_wait_s: int = 300):
    """Step 2: move every PDF from staging to dest_dir.

    Keeps retrying ALL pending files together (every 1 s) so that as the
    user naturally closes PDF viewer windows the moves happen automatically.
    No window needs to be closed before the next file can be attempted.
    Total patience: max_wait_s seconds (default 5 min).
    """
    pending = list(generated)   # list of (src Path, dst Path)
    start = time.time()

    while pending:
        if time.time() - start > max_wait_s:
            break
        still_locked = []
        for src, dst in pending:
            try:
                shutil.move(str(src), str(dst))
                print(f"  moved  {src.name}  \u2192  {dst.parent}")
            except PermissionError:
                still_locked.append((src, dst))
            except FileNotFoundError:
                print(f"  WARN  {src.name} already gone — skipped")
        pending = still_locked
        if pending:
            time.sleep(1)   # wait 1 s then re-try all remaining files

    if pending:
        print(f"\n  WARNING: {len(pending)} PDF(s) still locked after {max_wait_s} s"
              f" (close their viewer windows and re-run Step 2 manually if needed):")
        for src, _ in pending:
            print(f"    {src}")




def main():
    import argparse
    import fnmatch
    import tempfile

    parser = argparse.ArgumentParser(description="Convert workspace ENSDF files to PDF.")
    parser.add_argument("input", help="ENSDF file, dataset name, element, or glob")
    parser.add_argument("--jar", default=os.environ.get("ENSDF_NDS_JAR"),
                        help="McMaster-MSU Java NDS JAR (or set ENSDF_NDS_JAR)")
    parser.add_argument("--open", action="store_true", help="Open generated PDFs")
    parser.add_argument("--system", action="store_true", help="Use the system PDF viewer")
    args = parser.parse_args()
    workspace = Path.cwd()
    if args.jar:
        jar = Path(args.jar).expanduser().resolve()
        if not jar.is_file():
            parser.error(f"Java NDS JAR not found: {jar}")
    else:
        jars = sorted(workspace.rglob("McMaster_MSU_JAVA_NDS_v*.jar"))
        if len(jars) != 1:
            parser.error("Provide the Java NDS JAR using --jar or ENSDF_NDS_JAR.")
        jar = jars[0].resolve()
    if not shutil.which("java"):
        parser.error("Java executable not found on PATH.")
    supplied = Path(args.input).expanduser()
    if supplied.is_file():
        files = [supplied.resolve()]
    else:
        pattern = args.input.replace("\\", "/")
        if not pattern.lower().endswith(".ens"):
            pattern += "*.ens" if pattern.isalpha() else ".ens"
        files = sorted(
            path.resolve() for path in workspace.rglob("*.ens")
            if fnmatch.fnmatch(path.name.casefold(), pattern.casefold())
            or fnmatch.fnmatch(path.relative_to(workspace).as_posix().casefold(), pattern.casefold())
        )
    if not files:
        parser.error(f"No ENSDF files match: {args.input}")
    destinations = []
    for path in files:
        parent = path.parent.parent if path.parent.name.lower() == "new" else path.parent
        destinations.append(parent / "pdf" / (path.stem + ".pdf"))
    if len(set(destinations)) != len(destinations):
        parser.error("Selected files would produce duplicate PDF paths.")
    existing = [path for path in destinations if path.exists()]
    if existing:
        parser.error(f"PDF already exists; refusing to overwrite: {existing[0]}")
    with tempfile.TemporaryDirectory(prefix="ensdf-pdf-") as temp:
        generated = []
        for index, (source, destination) in enumerate(zip(files, destinations)):
            staging = Path(temp) / str(index)
            staging.mkdir()
            pdf = run_java(source, str(jar), staging)
            if pdf is None:
                raise SystemExit(f"PDF conversion failed: {source}")
            generated.append((pdf, destination))
        for pdf, destination in generated:
            destination.parent.mkdir(parents=True, exist_ok=True)
            move_all_pdfs([(pdf, destination)], destination.parent)
            if not destination.is_file():
                raise SystemExit(f"Could not move generated PDF to {destination}")
            if args.open:
                if not args.system and shutil.which("code"):
                    subprocess.run(["code", str(destination)], check=True)
                elif os.name == "nt":
                    os.startfile(str(destination))
                else:
                    import sys
                    subprocess.run(["open" if sys.platform == "darwin" else "xdg-open",
                                    str(destination)], check=True)


if __name__ == "__main__":
    main()
