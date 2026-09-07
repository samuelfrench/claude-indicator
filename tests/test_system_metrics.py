import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from claude_widget import (
    DiskMetrics,
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

    def test_one_interface_reset_cannot_be_masked_by_another_growth(self):
        routes = (
            ROUTE_HEADER
            + route_line("eth0", metric=100)
            + route_line("eth1", metric=100)
        )
        self._write(routes, {"eth0": (1000, 1000), "eth1": (1000, 1000)})
        reader = self._reader()
        reader.read()

        self.clock.value = 12.0
        self._write(routes, {"eth0": (100, 100), "eth1": (2900, 2900)})
        reset = reader.read()
        self.assertEqual((reset.net_rx_bps, reset.net_tx_bps), (0.0, 0.0))

        self.clock.value = 14.0
        self._write(routes, {"eth0": (300, 500), "eth1": (3100, 3300)})
        recovered = reader.read()
        self.assertEqual(
            (recovered.net_rx_bps, recovered.net_tx_bps),
            (200.0, 400.0),
        )

    def test_missing_route_or_selected_counter_is_honestly_unavailable(self):
        self._write(ROUTE_HEADER, {"eth0": (10, 20)})
        reader = self._reader()
        no_route = reader.read()
        self.assertFalse(no_route.net_available)
        self.assertEqual(no_route.net_interfaces, ())
        self.assertEqual(no_route.net_error, "")

        self.clock.value = 13.0
        routes = ROUTE_HEADER + route_line("eth0")
        self._write(routes, {"docker0": (1000, 2000)})
        missing_counter = reader.read()
        self.assertFalse(missing_counter.net_available)
        self.assertEqual(missing_counter.net_interfaces, ("eth0",))
        self.assertEqual(missing_counter.net_error, "counter-missing")

        self.clock.value = 16.0
        self._write(routes, {"eth0": (50000, 80000)})
        recovered = reader.read()
        self.assertTrue(recovered.net_available)
        self.assertEqual((recovered.net_rx_bps, recovered.net_tx_bps), (0.0, 0.0))

    def test_route_read_failure_is_explicit_and_clears_baseline(self):
        routes = ROUTE_HEADER + route_line("eth0")
        self._write(routes, {"eth0": (100, 200)})
        reader = self._reader()
        reader.read()

        (self.proc / "net" / "route").unlink()
        failed = reader.read()
        self.assertFalse(failed.net_available)
        self.assertEqual(failed.net_interfaces, ())
        self.assertEqual(failed.net_error, "route-read")

        self.clock.value = 12.0
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


def diskstats_line(name: str, *, sectors_read=0, sectors_written=0, io_ticks=0) -> str:
    return (
        f"   8       0 {name} 10 0 {sectors_read} 5 20 0 {sectors_written} 7 0 "
        f"{io_ticks} 12 0 0 0 0 0 0\n"
    )


class FakeStatvfs:
    def __init__(self, frsize, blocks, bfree, bavail):
        self.f_frsize = frsize
        self.f_blocks = blocks
        self.f_bfree = bfree
        self.f_bavail = bavail


class SystemMetricsDiskReaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.proc = root / "proc"
        self.sys = root / "sys"
        (self.proc / "net").mkdir(parents=True)
        (self.sys / "block").mkdir(parents=True)
        (self.proc / "stat").write_text("cpu  1 0 1 8 0 0 0 0\n")
        (self.proc / "meminfo").write_text(
            "MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\n"
        )
        (self.proc / "net" / "route").write_text(ROUTE_HEADER)
        (self.proc / "net" / "dev").write_text(dev_text({}))
        (self.proc / "mounts").write_text("")
        self.clock = ManualClock()
        self.statvfs_results: dict[str, FakeStatvfs] = {}
        self.statvfs_calls: list[str] = []

    def _add_block(
        self,
        name: str,
        *,
        physical=True,
        rotational=False,
        size_sectors=1000,
        model="",
        partitions=(),
        hidden=False,
    ):
        block = self.sys / "block" / name
        block.mkdir()
        (block / "size").write_text(f"{size_sectors}\n")
        (block / "queue").mkdir()
        (block / "queue" / "rotational").write_text("1\n" if rotational else "0\n")
        (block / "hidden").write_text("1\n" if hidden else "0\n")
        if physical:
            (block / "device").mkdir()
            (block / "device" / "model").write_text(f"{model}\n")
        for partition in partitions:
            (block / partition).mkdir()

    def _write_diskstats(self, *lines: str):
        (self.proc / "diskstats").write_text("".join(lines))

    def _statvfs(self, path):
        self.statvfs_calls.append(path)
        result = self.statvfs_results.get(path)
        if result is None:
            raise OSError("no such filesystem")
        return result

    def _reader(self):
        with patch("claude_widget.subprocess.run", side_effect=FileNotFoundError):
            return SystemMetricsReader(
                proc_root=self.proc,
                sys_root=self.sys,
                monotonic=self.clock,
                statvfs=self._statvfs,
            )

    def test_discovers_only_physical_unhidden_disks_sorted_by_name(self):
        self._add_block("sda", rotational=True, size_sectors=1953525168, model="WDC WD10EZEX")
        self._add_block("nvme0n1", size_sectors=3907029168, model="WD_BLACK SN7100")
        self._add_block("loop0", physical=False)
        self._add_block("zram0", physical=False)
        self._add_block("sdz", hidden=True)
        self._write_diskstats(
            diskstats_line("sda", sectors_read=100),
            diskstats_line("nvme0n1", sectors_read=200),
            diskstats_line("loop0", sectors_read=300),
        )
        reader = self._reader()

        metrics = reader.read()

        self.assertEqual([disk.name for disk in metrics.disks], ["nvme0n1", "sda"])
        nvme, sda = metrics.disks
        self.assertIsInstance(nvme, DiskMetrics)
        self.assertEqual(nvme.model, "WD_BLACK SN7100")
        self.assertFalse(nvme.rotational)
        self.assertEqual(nvme.size_bytes, 3907029168 * 512)
        self.assertTrue(sda.rotational)
        self.assertEqual(sda.model, "WDC WD10EZEX")
        self.assertEqual(sda.size_bytes, 1953525168 * 512)
        self.assertEqual(metrics.disk_error, "")

    def test_first_sample_is_zero_then_rates_and_busy_use_elapsed_time(self):
        self._add_block("sda")
        self._write_diskstats(
            diskstats_line("sda", sectors_read=1000, sectors_written=2000, io_ticks=500)
        )
        reader = self._reader()

        first = reader.read()
        self.assertEqual(
            (first.disks[0].read_bps, first.disks[0].write_bps, first.disks[0].busy_pct),
            (0.0, 0.0, 0.0),
        )

        self.clock.value = 12.0
        self._write_diskstats(
            diskstats_line("sda", sectors_read=1400, sectors_written=2100, io_ticks=1500)
        )
        second = reader.read()

        disk = second.disks[0]
        self.assertEqual(disk.read_bps, 400 * 512 / 2)
        self.assertEqual(disk.write_bps, 100 * 512 / 2)
        self.assertEqual(disk.busy_pct, 50.0)

    def test_busy_percent_is_clamped_and_counter_reset_rebaselines_only_that_disk(self):
        self._add_block("sda")
        self._add_block("sdb")
        self._write_diskstats(
            diskstats_line("sda", sectors_read=1000, io_ticks=1000),
            diskstats_line("sdb", sectors_read=1000, io_ticks=1000),
        )
        reader = self._reader()
        reader.read()

        self.clock.value = 11.0
        self._write_diskstats(
            diskstats_line("sda", sectors_read=10, io_ticks=5),
            diskstats_line("sdb", sectors_read=2024, io_ticks=2100),
        )
        metrics = reader.read()

        by_name = {disk.name: disk for disk in metrics.disks}
        self.assertEqual((by_name["sda"].read_bps, by_name["sda"].busy_pct), (0.0, 0.0))
        self.assertEqual(by_name["sdb"].read_bps, 1024 * 512)
        self.assertEqual(by_name["sdb"].busy_pct, 100.0)

        self.clock.value = 13.0
        self._write_diskstats(
            diskstats_line("sda", sectors_read=210, io_ticks=205),
            diskstats_line("sdb", sectors_read=2024, io_ticks=2100),
        )
        after = {disk.name: disk for disk in reader.read().disks}
        self.assertEqual(after["sda"].read_bps, 100 * 512)
        self.assertEqual(after["sda"].busy_pct, 10.0)
        self.assertEqual((after["sdb"].read_bps, after["sdb"].busy_pct), (0.0, 0.0))

    def test_filesystem_usage_sums_each_disk_partition_once(self):
        self._add_block("sda", partitions=("sda1",))
        self._add_block("nvme0n1", partitions=("nvme0n1p1", "nvme0n1p2"))
        self._add_block("nvme1n1")
        self._write_diskstats(
            diskstats_line("sda"), diskstats_line("nvme0n1"), diskstats_line("nvme1n1")
        )
        (self.proc / "mounts").write_text(
            "/dev/nvme0n1p2 / ext4 rw 0 0\n"
            "/dev/loop0 /snap/core 0 squashfs ro 0 0\n"
            "/dev/nvme0n1p1 /boot/efi vfat rw 0 0\n"
            "/dev/nvme0n1p2 /mnt/bind ext4 rw 0 0\n"
            "/dev/sda1 /media/sam/HDD\\040two ext4 rw 0 0\n"
            "/dev/mapper/vg-lv /crypt ext4 rw 0 0\n"
        )
        self.statvfs_results = {
            "/": FakeStatvfs(4096, 1000, 400, 300),
            "/boot/efi": FakeStatvfs(512, 100, 50, 50),
            "/media/sam/HDD two": FakeStatvfs(4096, 2000, 1000, 1000),
        }
        reader = self._reader()

        by_name = {disk.name: disk for disk in reader.read().disks}

        self.assertEqual(by_name["nvme0n1"].mount_points, ("/", "/boot/efi"))
        self.assertEqual(
            by_name["nvme0n1"].fs_used_bytes, 600 * 4096 + 50 * 512
        )
        self.assertEqual(
            by_name["nvme0n1"].fs_total_bytes, 900 * 4096 + 100 * 512
        )
        self.assertEqual(by_name["sda"].mount_points, ("/media/sam/HDD two",))
        self.assertEqual(by_name["sda"].fs_used_bytes, 1000 * 4096)
        self.assertEqual(by_name["sda"].fs_total_bytes, 2000 * 4096)
        self.assertAlmostEqual(by_name["sda"].fs_used_pct, 50.0)
        self.assertEqual(by_name["nvme1n1"].mount_points, ())
        self.assertIsNone(by_name["nvme1n1"].fs_used_pct)
        self.assertEqual(self.statvfs_calls.count("/"), 1)

    def test_failed_statvfs_leaves_disk_without_usage_not_crashing(self):
        self._add_block("sda", partitions=("sda1",))
        self._write_diskstats(diskstats_line("sda"))
        (self.proc / "mounts").write_text("/dev/sda1 /gone ext4 rw 0 0\n")
        reader = self._reader()

        disk = reader.read().disks[0]

        self.assertEqual(disk.mount_points, ("/gone",))
        self.assertIsNone(disk.fs_used_pct)

    def test_missing_diskstats_reports_error_and_clears_baseline(self):
        self._add_block("sda")
        self._write_diskstats(diskstats_line("sda", sectors_read=1000, io_ticks=100))
        reader = self._reader()
        reader.read()

        self.clock.value = 12.0
        (self.proc / "diskstats").unlink()
        broken = reader.read()
        self.assertEqual(broken.disks, ())
        self.assertEqual(broken.disk_error, "diskstats-read")

        self.clock.value = 14.0
        self._write_diskstats(diskstats_line("sda", sectors_read=9000, io_ticks=1900))
        recovered = reader.read()
        self.assertEqual(recovered.disk_error, "")
        self.assertEqual(
            (recovered.disks[0].read_bps, recovered.disks[0].busy_pct), (0.0, 0.0)
        )

    def test_disk_missing_from_diskstats_or_block_dir_is_skipped(self):
        self._add_block("sda")
        self._add_block("sdb")
        self._write_diskstats(diskstats_line("sda"))
        reader = self._reader()

        metrics = reader.read()

        self.assertEqual([disk.name for disk in metrics.disks], ["sda"])
        self.assertEqual(metrics.disk_error, "")

    def test_no_block_dir_is_honest_and_empty(self):
        (self.sys / "block").rmdir()
        self._write_diskstats(diskstats_line("sda"))
        reader = self._reader()

        metrics = reader.read()

        self.assertEqual(metrics.disks, ())
        self.assertEqual(metrics.disk_error, "block-read")


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

    def test_formatter_promotes_and_caps_fractional_boundaries(self):
        self.assertEqual(format_network_rate(1023.49), "1023 B/s")
        self.assertEqual(format_network_rate(1023.5), "1.0 KiB/s")
        self.assertEqual(
            format_network_rate(1023.5 * 1024, compact=True),
            "1.0M/s",
        )
        capped_rate = 999.5 * 1024**4
        self.assertEqual(format_network_rate(capped_rate), "999+ TiB/s")
        self.assertEqual(
            format_network_rate(capped_rate, compact=True),
            "999+T/s",
        )

    def test_formatter_marks_invalid_rates_unavailable(self):
        for value in (None, -1, float("nan"), float("inf"), "bad"):
            with self.subTest(value=value):
                self.assertEqual(format_network_rate(value), "—")


if __name__ == "__main__":
    unittest.main()
