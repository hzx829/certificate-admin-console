"""Export this task's native Codex JSONL with declared, narrow redactions.

--finalize waits for the current turn to finish, exports its final response too,
commits the evidence and packages main. --package-only verifies and packages the
already committed evidence. Original delivery bundles are never overwritten.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REASONS = Counter()
PRIVATE_FIELDS = {
    "base_instructions": "platform instructions",
    "developer_instructions": "platform instructions",
    "system_instructions": "platform instructions",
    "encrypted_content": "hidden reasoning payload",
    "internal_chat_message_metadata_passthrough": "internal platform metadata",
    "creator_user_id": "private account identifier",
    "creator_account_id": "private account identifier",
}


def replacement(reason):
    REASONS[reason] += 1
    return f"[REDACTED: {reason}]"


def scrub(value):
    if isinstance(value, dict):
        return {key:replacement(PRIVATE_FIELDS[key]) if key in PRIVATE_FIELDS and item is not None else scrub(item)
                for key,item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return replacement("image binary; original tool action and text retained")
    return value


def redact(record):
    record = scrub(record)
    payload = record.get("payload", {})
    if record.get("type") == "world_state":
        record["payload"] = replacement("internal platform state")
    elif record.get("type") == "compacted":
        record["payload"] = replacement("internal context compaction; original chronological interactions retained")
    elif isinstance(payload, dict):
        if payload.get("role") in ("system", "developer"):
            payload["content"] = replacement("platform instructions")
        elif payload.get("type") == "reasoning" or (payload.get("role") == "assistant" and payload.get("channel") == "analysis"):
            for key in ("content", "summary", "text"):
                if key in payload:
                    payload[key] = replacement("hidden reasoning")
        elif payload.get("type") == "agent_reasoning":
            payload["text"] = replacement("hidden reasoning")
        if record.get("type") == "turn_context" and payload.get("summary"):
            payload["summary"] = replacement("internal context summary")
    return record


def read_records(source):
    # An active writer may be partway through its final line. Read complete lines only.
    lines = source.read_bytes().splitlines(keepends=True)
    complete = [line for line in lines if line.endswith(b"\n")]
    records = [json.loads(line) for line in complete]
    return records, b"".join(complete)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def export(source, records, raw):
    REASONS.clear()
    session = next(r["payload"] for r in records if r["type"] == "session_meta")
    session_id = session.get("session_id") or session["id"]
    folder = ROOT / "ai" / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{session_id}.jsonl"
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(redact(record), ensure_ascii=False, separators=(",", ":"))+"\n")
    models = sorted({r["payload"]["model"] for r in records if r["type"] == "turn_context" and "model" in r["payload"]})
    commits = git("rev-list", "--reverse", "HEAD").splitlines()
    fields = ["session_id","tool","model","started_at","ended_at","export_file","purpose","related_commits"]
    with (ROOT / "ai" / "session-index.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerow(dict(zip(fields,[session_id,"Codex desktop",";".join(models),records[0]["timestamp"],records[-1]["timestamp"],
            f"ai/sessions/{session_id}.jsonl","Assessment planning, implementation, correction, automated and Chrome verification, documentation",";".join(commits)])))
    manifest = {"exported_at":datetime.now(UTC).isoformat(),"native_source_name":source.name,"session_id":session_id,
        "record_count":len(records),"exported_through":records[-1]["timestamp"],
        "source_prefix_sha256":hashlib.sha256(raw).hexdigest(),"export_sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),
        "record_types":dict(Counter(r["type"] for r in records)),"redactions":dict(REASONS),
        "format":"Native chronological JSONL, with explicitly declared redactions; no reconstructed or selected messages."}
    (ROOT / "ai" / "export-manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(f"Exported {len(records)} native records through {manifest['exported_through']}",flush=True)


def package_main(push=False):
    if git("branch", "--show-current") != "main":
        raise SystemExit("Package the selected main branch, not a development branch.")
    if git("status", "--porcelain"):
        raise SystemExit("Commit the intended submission files before packaging; working tree is not clean.")
    manifest = json.loads((ROOT / "ai" / "export-manifest.json").read_text(encoding="utf-8"))
    evidence_path = f"ai/sessions/{manifest['session_id']}.jsonl"
    evidence = subprocess.check_output(["git", "show", f"HEAD:{evidence_path}"], cwd=ROOT)
    if hashlib.sha256(evidence).hexdigest() != manifest["export_sha256"]:
        raise SystemExit("Committed evidence does not match its manifest.")
    with (ROOT / "ai" / "session-index.csv").open(encoding="utf-8", newline="") as file:
        sessions = list(csv.DictReader(file))
    if not all((ROOT / row["export_file"]).is_file() for row in sessions):
        raise SystemExit("An indexed AI export is missing.")
    sha = git("rev-parse", "HEAD")
    bundle = ROOT / "artifacts" / "certificate-admin-console-main.bundle"
    bundle.parent.mkdir(exist_ok=True)
    git("bundle", "create", str(bundle), "--all")
    git("bundle", "verify", str(bundle))
    refs = dict(line.split(maxsplit=1)[::-1] for line in git("bundle", "list-heads", str(bundle)).splitlines())
    if refs.get("refs/heads/main") != sha:
        raise SystemExit("Bundle main does not point to the intended submission commit.")
    submission = {"packaged_at":datetime.now(UTC).isoformat(), "branch":"main", "final_commit":sha,
        "bundle":bundle.name, "bundle_sha256":hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "evidence_through":manifest["exported_through"], "evidence_sha256":manifest["export_sha256"],
        "bundle_verified":True, "working_tree":"",
        "original_delivery_commit":"45b2c1657803d9b0f887ffa94395c1a22cfd1603",
        "phase":"Improved main, including user-authorized changes after the timed delivery",
        "repository_url":git("remote", "get-url", "origin").removesuffix(".git"),
        "pending_submission_items":["Candidate-only written answers and personal no-AI confirmation", "Reviewer read access to the private repository"]}
    if push:
        print(git("push", "--set-upstream", "origin", "main"), flush=True)
        remote_sha = git("ls-remote", "origin", "refs/heads/main").split()[0]
        if remote_sha != sha:
            raise SystemExit("Remote main does not match the packaged commit.")
        submission["pushed_commit"] = remote_sha
        submission["remote_verified"] = True
    (ROOT / "artifacts" / "main-submission.json").write_text(json.dumps(submission,indent=2),encoding="utf-8")
    print(json.dumps(submission),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--finalize", action="store_true")
    parser.add_argument("--package-only", action="store_true")
    parser.add_argument("--push", action="store_true", help="Explicitly push origin main after packaging and verify its SHA")
    args = parser.parse_args()
    if args.package_only:
        if args.source or args.finalize:
            parser.error("--package-only cannot be combined with --source or --finalize")
        package_main(push=args.push)
        raise SystemExit(0)
    if args.source is None:
        parser.error("--source is required for native evidence export")
    if args.push and not args.finalize:
        parser.error("--push requires --finalize or --package-only")
    records, raw = read_records(args.source)
    if args.finalize:
        started = [r["payload"] for r in records if r["type"] == "event_msg" and r["payload"].get("type") == "task_started"]
        target = started[-1]["turn_id"]
        print(f"Waiting for current turn {target} to finish before final evidence export.",flush=True)
        deadline = time.monotonic()+1800
        while time.monotonic() < deadline:
            records, raw = read_records(args.source)
            if any(r["type"] == "event_msg" and r["payload"].get("type") == "task_complete" and r["payload"].get("turn_id") == target for r in records):
                break
            time.sleep(1)
        else:
            raise SystemExit("Turn did not finish within 30 minutes. Re-run export; do not claim evidence is complete.")
    export(args.source, records, raw)
    if args.finalize:
        paths = ["ai/sessions", "ai/session-index.csv", "ai/export-manifest.json"]
        git("add", *paths)
        if git("diff", "--cached", "--name-only", "--", *paths):
            print(git("commit", "-m", "docs: finalize main submission interaction evidence", "--", *paths),flush=True)
        package_main(push=args.push)
