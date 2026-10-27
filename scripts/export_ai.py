"""Export this task's native Codex JSONL with declared, narrow redactions.

--finalize waits for the current turn to finish, exports its final response too,
commits the evidence and produces a Git bundle. No transcript is reconstructed.
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
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
        git("add", "ai/sessions", "ai/session-index.csv", "ai/export-manifest.json")
        if git("diff", "--cached", "--name-only"):
            print(git("commit", "-m", "docs: finalize native AI evidence including delivery response"),flush=True)
        sha = git("rev-parse", "HEAD")
        bundle = ROOT / "artifacts" / "certificate-admin-console.bundle"
        git("bundle", "create", str(bundle), "--all")
        submission = {"final_commit":sha,"bundle":str(bundle),"bundle_sha256":hashlib.sha256(bundle.read_bytes()).hexdigest(),
                      "evidence_through":records[-1]["timestamp"],"working_tree":git("status", "--porcelain")}
        (ROOT / "artifacts" / "submission.json").write_text(json.dumps(submission,indent=2),encoding="utf-8")
        print(json.dumps(submission),flush=True)
