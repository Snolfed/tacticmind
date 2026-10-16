"""Engine process: messages after each depth, stop, and successive requests without restarting."""

import time

from tacticmind.engine.process import CompareEvent, DoneEvent, EngineClient, EngineEvent, InfoEvent


def wait_for(client: EngineClient, kind: type, req_id: int, timeout: float = 30.0) -> list[EngineEvent]:
    collected: list[EngineEvent] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event in client.poll():
            collected.append(event)
            if isinstance(event, kind) and event.id == req_id:
                return collected
        time.sleep(0.01)
    raise TimeoutError(f"No {kind.__name__} message for request {req_id}")


def test_engine_process_protocol() -> None:
    client = EngineClient()
    try:
        # 1) A long analysis, interrupted by a new request.
        first = client.analyze("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", time_ms=60_000)
        # Wait until the first analysis has really started (process startup on a busy machine can be slow),
        # otherwise the process sees both requests at once and rightly skips the first one.
        early = wait_for(client, InfoEvent, first)
        second = client.analyze("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", time_ms=5_000, multi_pv=3)
        events = early + wait_for(client, DoneEvent, second)
        infos = [e.info for e in events if isinstance(e, InfoEvent) and e.id == second]
        assert infos, "the engine should send info after each depth"
        assert [i.depth for i in infos] == list(range(1, len(infos) + 1))
        last = infos[-1]
        assert last.best_move == "d1d8" and last.mate_in == 1
        for field in ("depth", "score", "pv", "multi_pv", "nodes", "nps", "cutoffs", "tt_hits", "time_ms"):
            assert hasattr(last, field)
        # The first request was interrupted (stopped=True) and did not block the second one.
        done_first = [e for e in events if isinstance(e, DoneEvent) and e.id == first]
        assert done_first and done_first[0].stopped is True

        # 2) Comparison mode in the same process.
        cmp_id = client.compare("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 2)
        cmp_event = wait_for(client, CompareEvent, cmp_id)[-1]
        assert isinstance(cmp_event, CompareEvent)
        result = cmp_event.result
        assert result.minimax is not None
        assert result.minimax.score == result.alpha_beta.score
        assert result.alpha_beta.nodes < result.minimax.nodes
    finally:
        client.close()
