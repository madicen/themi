from tests.evals.pacing import MinuteLimiter


async def test_the_limiter_waits_once_a_minute_is_full() -> None:
    moment = [0.0]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(round(seconds, 1))
        moment[0] += seconds

    limiter = MinuteLimiter(3, now=lambda: moment[0], sleep=sleep)
    for _ in range(3):
        await limiter.wait()
        moment[0] += 1
    assert waits == []  # 3 calls in a minute are fine
    await limiter.wait()  # the 4th waits until the first is a minute old
    assert waits == [57.1]
    moment[0] += 120
    await limiter.wait()
    assert len(waits) == 1
