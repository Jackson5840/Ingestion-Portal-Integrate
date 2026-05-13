#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


MAIN_ROOT = Path("/data/app/tomcat/apache-tomcat-7.0.54/webapps/neuroMorpho")
TOMCAT_USER = "cliusr"
TOMCAT_PASSWORD = "100Neuraldb"
TOMCAT_RELOAD_URL = "http://localhost:8080/manager/text/reload?path=/neuroMorpho/"
SOLR_BASE = "http://localhost:8983/solr"
SOLR_CORES = ["neuron", "morphometry", "search-Review", "pvec", "search-Main"]


def bundle_candidates(base_dir: Path):
    result = []
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "files").is_dir() or (entry / "jsp").is_dir() or (entry / "xml").is_dir():
            result.append(entry)
    return result


def copy_tree_contents(src: Path, dest: Path):
    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        target_root = dest / rel
        target_root.mkdir(parents=True, exist_ok=True)
        for dirname in dirs:
            (target_root / dirname).mkdir(parents=True, exist_ok=True)
        for filename in files:
            src_file = root_path / filename
            dest_file = target_root / filename
            shutil.copy2(src_file, dest_file)


def import_bundle(bundle_dir: Path):
    files_dir = bundle_dir / "files"
    jsp_dir = bundle_dir / "jsp"
    xml_dir = bundle_dir / "xml"

    if not MAIN_ROOT.exists():
        raise FileNotFoundError("Main site root not found: {}".format(MAIN_ROOT))

    copied = []

    if files_dir.is_dir():
        copy_tree_contents(files_dir, MAIN_ROOT)
        copied.append(str(files_dir))

    if jsp_dir.is_dir():
        MAIN_ROOT.mkdir(parents=True, exist_ok=True)
        for item in sorted(jsp_dir.iterdir()):
            if item.is_file():
                shutil.copy2(item, MAIN_ROOT / item.name)
                copied.append(str(item))

    if xml_dir.is_dir():
        target_xml = MAIN_ROOT / "xml"
        target_xml.mkdir(parents=True, exist_ok=True)
        for item in sorted(xml_dir.iterdir()):
            if item.is_file():
                shutil.copy2(item, target_xml / item.name)
                copied.append(str(item))

    return copied


def run_command(command):
    print("Running:", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError("Command failed with code {}: {}".format(result.returncode, " ".join(command)))


def run_mainflow():
    run_command(["curl", "-u", "{}:{}".format(TOMCAT_USER, TOMCAT_PASSWORD), TOMCAT_RELOAD_URL])
    time.sleep(1)
    for core in SOLR_CORES:
        run_command(["curl", "{}/{}/dataimport?command=full-import".format(SOLR_BASE, core)])
        time.sleep(1)
    run_command(["curl", "{}/{}/dataimport?command=status".format(SOLR_BASE, "search-Main")])


def prompt_choice(prompt, options):
    while True:
        print(prompt)
        for key, label in options:
            print("  {}. {}".format(key, label))
        answer = input("> ").strip().lower()
        for key, _ in options:
            if answer == key:
                return answer
        print("Invalid selection.\n")


def choose_bundle():
    cwd = Path.cwd()
    bundles = bundle_candidates(cwd)
    if not bundles:
        print("No archive bundle folders found in current directory.")
        return None

    print("Available archive bundles:")
    for index, bundle in enumerate(bundles, start=1):
        print("  {}. {}".format(index, bundle.name))

    while True:
        answer = input("Select bundle number: ").strip()
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(bundles):
                return bundles[index - 1]
        print("Invalid bundle number.\n")


def main():
    while True:
        choice = prompt_choice(
            "Choose an action:",
            [("1", "Import archive files"), ("2", "Run mainflow"), ("q", "Quit")],
        )

        if choice == "q":
            print("Bye.")
            return 0

        if choice == "1":
            bundle = choose_bundle()
            if bundle is None:
                continue
            try:
                copied = import_bundle(bundle)
                print("\nImport complete for {}.".format(bundle.name))
                print("Updated {} item(s).".format(len(copied)))
            except Exception as exc:
                print("Import failed: {}".format(exc), file=sys.stderr)
        elif choice == "2":
            try:
                run_mainflow()
                print("\nMainflow completed.")
            except Exception as exc:
                print("Mainflow failed: {}".format(exc), file=sys.stderr)

        print()


if __name__ == "__main__":
    raise SystemExit(main())
