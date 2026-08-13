#!/usr/bin/env python3
"""Demo prep: create today's anomaly-response procedure execution and pin
the deep-dive workbook's Response tab to it.

The Response tab embeds a procedure *execution* panel next to live
HTR-2 duty / bus current traces and the command-ACK log — the operator
works the procedure and watches their actions land in the telemetry on
the same screen. Galaxy's procedure panel binds a specific execution
rid (a template reference renders unbound), so each demo cycle:

    python3 goce_response_prep.py            # create + pin
    python3 goce_response_prep.py --pin <execution-rid>   # pin existing

Run this BEFORE opening the workbook in the browser (open app tabs
clobber API updates with their stale state).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from nominal.core import NominalClient
from nominal.core._utils.grpc_tools import create_grpc_channel
from nominal.protos.procedures.v1 import procedures_pb2 as pp
from nominal.protos.procedures.v1.procedures_pb2_grpc import ProceduresServiceStub
from nominal.protos.procedures.executions.v1 import procedure_executions_pb2 as pe
from nominal.protos.procedures.executions.v1.procedure_executions_pb2_grpc import (
    ProcedureExecutionsServiceStub,
)

PROCEDURE_RID = "ri.scout.cerulean-staging.procedure.f789cd49-0e68-4d23-b37f-e8d162413c15"
SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="space_demo_prod")
    parser.add_argument("--satellite", type=int, default=7)
    parser.add_argument("--pin", default=None,
                        help="pin an existing execution rid instead of creating one")
    args = parser.parse_args()

    exec_rid = args.pin
    if exec_rid is None:
        client = NominalClient.from_profile(args.profile)
        b = client._clients
        channel = create_grpc_channel(
            api_base_url=b._api_base_url, service_config=b._service_config,
            user_agent=b._user_agent, auth_header=b.auth_header,
            header_provider=b.header_provider,
        )
        proc = ProceduresServiceStub(channel)
        execs = ProcedureExecutionsServiceStub(channel)
        commit = proc.GetProcedure(pp.GetProcedureRequest(rid=PROCEDURE_RID)).procedure.commit
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        resp = execs.CreateProcedureExecution(pe.CreateProcedureExecutionRequest(
            procedure_rid=PROCEDURE_RID,
            procedure_commit_id=commit,
            title=f"GOCE-7 HTR-2 anomaly response — {stamp}",
            description="Live demo execution (created by goce_response_prep.py).",
            start_immediately=True,
        ))
        exec_rid = resp.procedure_execution.rid
        print(f"Created execution: {exec_rid}")

    # Rebuild the deep-dive workbook with the Response panel pinned.
    cmd = [
        sys.executable, str(SCRIPT_DIR / "goce_deepdive_builder.py"),
        "--profile", args.profile,
        "--satellite", str(args.satellite),
        "--procedure-execution", exec_rid,
    ]
    print("Pinning Response tab:", " ".join(cmd[1:]))
    subprocess.run(cmd, check=True)
    print(f"\nDone. Execution pinned: {exec_rid}")
    print("Now open the workbook fresh in the browser (Response tab).")


if __name__ == "__main__":
    main()
