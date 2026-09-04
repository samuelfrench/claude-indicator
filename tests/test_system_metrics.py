import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_widget import (
    SystemMetricsReader,
    _lowest_metric_default_interfaces,
    _parse_net_dev_bytes,
    format_network_rate,
)


ROUTE_HEADER = (
    "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
)


def route_line(
    iface: str,
    *,
    destination="00000000",
    flags="0003",
    metric=100,
    mask="00000000",
) -> str:
    return (
        f"{iface} {destination} 01010101 {flags} 0 0 {metric} "
        f"{mask} 0 0 0\n"
    )


def dev_text(counters: dict[str, tuple[int, int]]) -> str:
    lines = [
        "Inter-| Receive | Transmit\n",
        " face |bytes packets errs drop fifo frame compressed multicast|"
        "bytes packets errs drop fifo colls carrier compressed\n",
    ]
    for iface, (received, transmitted) in counters.items():
        values = [received, 1, 0, 0, 0, 0, 0, 0, transmitted, 1, 0, 0, 0, 0, 0, 0]
        lines.append(f" {iface}: " + " ".join(str(value) for value in values) + "\n")
    return "".join(lines)


class ManualClock:
    def __init__(self, value=10.0):
        self.value = value

    def __call__(self):
        return self.value


class NetworkParserTest(unittest.TestCase):
    def test_route_parser_selects_all_up_lowest_metric_defaults(self):
        routes = ROUTE_HEADER + "".join(
            [
                route_line("down0", flags="0000", metric=1),
                route_line("reject0", flags="0201", metric=1),
                route_line("eth9", metric=200),
                route_line("eth1", flags="0001", metric=100),
                route_line("eth0", metric=100),
                route_line("docker0", destination="000011AC", metric=0),
                route_line("tailscale0", mask="00FFFFFF", metric=0),
                "malformed default route\n",
            ]
        )

        self.assertEqual(
            _lowest_metric_default_interfaces(routes),
            ("eth0", "eth1"),
        )

    def test_route_parser_requires_valid_up_nonreject_default(self):
        self.assertEqual(_lowest_metric_default_interfaces(""), ())
        self.assertEqual(
            _lowest_metric_default_interfaces(
                ROUTE_HEADER
                + route_line("down0", flags="0000")
                + route_line("reject0", flags="0201")
                + route_line("badmetric", metric="not-a-number")
            ),
            (),
        )

    def test_dev_parser_reads_only_valid_receive_transmit_byte_columns(self):
        text = dev_text({"lo": (50, 60), "eth0": (1234, 5678)})
        text += "broken: 1 2 3\n"
        text += "bad: nope 1 2 3 4 5 6 7 9 10 11 12 13 14 15 16\n"

        self.assertEqual(
            _parse_net_dev_bytes(text),
            {"lo": (50, 60), "eth0": (1234, 5678)},
        )


class SystemMetricsNetworkReaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proc = Path(self._tmp.name)
        (self.proc / "net").mkdir()
        (self.proc / "stat").write_text("cpu  1 0 1 8 0 0 0 0\n")
        (self.proc / "meminfo").write_text(
            "MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\n"
        )
        self.clock = ManualClock()

    def _write(self, routes: str, counters: dict[str, tuple[int, int]]):
        (self.proc / "net" / "route").write_text(routes)
        (self.proc / "net" / "dev").write_text(dev_text(counters))

    def _reader(self):
        with patch("claude_widget.subprocess.run", side_effect=FileNotFoundError):
            return SystemMetricsReader(
                proc_root=self.proc,
                monotonic=self.clock,
            )

    def test_rates_aggregate_equal_metric_interfaces_and_use_elapsed_time(self):
        routes = (
            ROUTE_HEADER
            + route_line("eth0", metric=100)
            + route_line("eth1", metric=100)
            + route_line("docker0", destination="000011AC", metric=0)
        )
        self._write(routes, {"eth0": (1000, 2000), "eth1": (500, 800), "docker0": (999999, 999999)})
        reader = self._reader()

        first = reader.read()
        self.assertTrue(first.net_available)
        self.assertEqual(first.net_interfaces, ("eth0", "eth1"))
        self.assertEqual((first.net_rx_bps, first.net_tx_bps), (0.0, 0.0))

        self.clock.value = 12.0
        self._write(routes, {"eth0": (1300, 2200), "eth1": (600, 900), "docker0": (1999999, 1999999)})
        second = reader.read()

        self.assertEqual(second.net_rx_bps, 200.0)
        self.assertEqual(second.net_tx_bps, 150.0)

    def test_route_change_and_counter_reset_replace_baseline_without_spike(self):
        eth0_route = ROUTE_HEADER + route_line("eth0")
        eth1_route = ROUTE_HEADER + route_line("eth1", metric=50)
        self._write(eth0_route, {"eth0": (100, 200), "eth1": (9000, 12000)})
        reader = self._reader()
        reader.read()

        self.clock.value = 13.0
        self._write(eth1_route, {"eth0": (500, 700), "eth1": (10000, 13000)})
        changed = reader.read()
        self.assertEqual(changed.net_interfaces, ("eth1",))
        self.assertEqual((changed.net_rx_bps, changed.net_tx_bps), (0.0, 0.0))

        self.clock.value = 15.0
        self._write(eth1_route, {"eth1": (10200, 13100)})
        steady = reader.read()
        self.assertEqual((steady.net_rx_bps, steady.net_tx_bps), (100.0, 50.0))

        self.clock.value = 18.0
        self._write(eth1_route, {"eth1": (20, 40)})
        reset = reader.read()
        self.assertEqual((reset.net_rx_bps, reset.net_tx_bps), (0.0, 0.0))

        self.clock.value = 20.0
        self._write(eth1_route, {"eth1": (220, 140)})
        after_reset = reader.read()
        self.assertEqual(
            (after_reset.net_rx_bps, after_reset.net_tx_bps),
            (100.0, 50.0),
        )

    def test_missing_route_or_selected_counter_is_honestly_unavailable(self):
        self._write(ROUTE_HEADER, {"eth0": (10, 20)})
        reader = self._reader()
        no_route = reader.read()
        self.assertFalse(no_route.net_available)
        self.assertEqual(no_route.net_interfaces, ())

        self.clock.value = 13.0
        routes = ROUTE_HEADER + route_line("eth0")
        self._write(routes, {"docker0": (1000, 2000)})
        missing_counter = reader.read()
        self.assertFalse(missing_counter.net_available)
        self.assertEqual(missing_counter.net_interfaces, ("eth0",))

        self.clock.value = 16.0
        self._write(routes, {"eth0": (50000, 80000)})
        recovered = reader.read()
        self.assertTrue(recovered.net_available)
        self.assertEqual((recovered.net_rx_bps, recovered.net_tx_bps), (0.0, 0.0))

    def test_nonpositive_monotonic_elapsed_resets_instead_of_spiking(self):
        routes = ROUTE_HEADER + route_line("eth0")
        self._write(routes, {"eth0": (100, 100)})
        reader = self._reader()
        reader.read()

        self._write(routes, {"eth0": (200, 300)})
        same_time = reader.read()
        self.assertEqual((same_time.net_rx_bps, same_time.net_tx_bps), (0.0, 0.0))

        self.clock.value = 12.0
        self._write(routes, {"eth0": (400, 500)})
        recovered = reader.read()
        self.assertEqual((recovered.net_rx_bps, recovered.net_tx_bps), (100.0, 100.0))


class NetworkRateFormatterTest(unittest.TestCase):
    def test_formatter_has_stable_binary_units_and_compact_variant(self):
        self.assertEqual(format_network_rate(0), "0 B/s")
        self.assertEqual(format_network_rate(1023), "1023 B/s")
        self.assertEqual(format_network_rate(1024), "1.0 KiB/s")
        self.assertEqual(format_network_rate(10 * 1024), "10 KiB/s")
        self.assertEqual(format_network_rate(1.5 * 1024**2), "1.5 MiB/s")
        self.assertEqual(
            format_network_rate(1.5 * 1024**2, compact=True),
            "1.5M/s",
        )

    def test_formatter_marks_invalid_rates_unavailable(self):
        for value in (None, -1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                self.assertEqual(format_network_rate(value), "—")


if __name__ == "__main__":
    unittest.main()
