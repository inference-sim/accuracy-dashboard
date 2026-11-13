def calculate_metrics(
    input_requests: list[tuple[str, int, int]],
    outputs: list[RequestFuncOutput],
    dur_s: float,
    tokenizer: PreTrainedTokenizerBase,
    selected_percentiles: list[float],
    goodput_config_dict: dict[str, float],
) -> tuple[BenchmarkMetrics, list[int]]:
    """Summarize ``outputs`` over ``dur_s`` seconds into metrics, plus each request's output length.

    Retokenizes text when the server sent no usage count, which may overcount slightly. Goodput counts
    a request whose TTFT, TPOT (0 for one token), and E2EL all meet ``goodput_config_dict``.
    """
    actual_output_lens: list[int] = []
    total_input = 0
    completed = 0
    good_completed = 0
    itls: list[float] = []
    tpots: list[float] = []
    all_tpots: list[float] = []
    ttfts: list[float] = []
    e2els: list[float] = []
    for i in range(len(outputs)):
        if outputs[i].success:
            output_len = outputs[i].output_tokens

            if not output_len:
                output_len = len(
                    tokenizer(outputs[i].generated_text, add_special_tokens=False).input_ids
                )
            actual_output_lens.append(output_len)
            total_input += input_requests[i][1]
            tpot = 0
            if output_len > 1:
                latency_minus_ttft = outputs[i].latency - outputs[i].ttft
                tpot = latency_minus_ttft / (output_len - 1)
                tpots.append(tpot)
            all_tpots.append(tpot)
            itls += outputs[i].itl
            ttfts.append(outputs[i].ttft)
            e2els.append(outputs[i].latency)
            completed += 1
        else:
            actual_output_lens.append(0)

    if goodput_config_dict:
        valid_metrics = []
        slo_values = []

        if "ttft" in goodput_config_dict:
            valid_metrics.append(ttfts)
            slo_values.append(goodput_config_dict["ttft"] / MILLISECONDS_TO_SECONDS_CONVERSION)
        if "tpot" in goodput_config_dict:
            valid_metrics.append(all_tpots)
            slo_values.append(goodput_config_dict["tpot"] / MILLISECONDS_TO_SECONDS_CONVERSION)
        if "e2el" in goodput_config_dict:
            valid_metrics.append(e2els)
            slo_values.append(goodput_config_dict["e2el"] / MILLISECONDS_TO_SECONDS_CONVERSION)

        for req_metric in zip(*valid_metrics, strict=False):
            is_good_req = all(s >= r for s, r in zip(slo_values, req_metric, strict=False))
            if is_good_req:
                good_completed += 1

    if completed == 0:
        warnings.warn(
            "All requests failed. This is likely due to a misconfiguration "
            "on the benchmark arguments.",
            stacklevel=2,
        )
    ttfts, tpots, itls, e2els = (np.asarray(v or 0) for v in (ttfts, tpots, itls, e2els))
    metrics = BenchmarkMetrics(
        completed=completed,
        total_input=total_input,
        total_output=sum(actual_output_lens),
        request_throughput=completed / dur_s,
        request_goodput=good_completed / dur_s,
        output_throughput=sum(actual_output_lens) / dur_s,
        total_token_throughput=(total_input + sum(actual_output_lens)) / dur_s,
        mean_ttft_ms=np.mean(ttfts) * 1000,
        std_ttft_ms=np.std(ttfts) * 1000,
        median_ttft_ms=np.median(ttfts) * 1000,
        percentiles_ttft_ms=[(p, np.percentile(ttfts, p) * 1000) for p in selected_percentiles],
        mean_tpot_ms=np.mean(tpots) * 1000,
        std_tpot_ms=np.std(tpots) * 1000,
        median_tpot_ms=np.median(tpots) * 1000,
        percentiles_tpot_ms=[(p, np.percentile(tpots, p) * 1000) for p in selected_percentiles],
        mean_itl_ms=np.mean(itls) * 1000,
        std_itl_ms=np.std(itls) * 1000,
        median_itl_ms=np.median(itls) * 1000,
        percentiles_itl_ms=[(p, np.percentile(itls, p) * 1000) for p in selected_percentiles],
        mean_e2el_ms=np.mean(e2els) * 1000,
        std_e2el_ms=np.std(e2els) * 1000,
        median_e2el_ms=np.median(e2els) * 1000,
        percentiles_e2el_ms=[(p, np.percentile(e2els, p) * 1000) for p in selected_percentiles],
    )

    return metrics, actual_output_lens
