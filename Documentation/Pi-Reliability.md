# Pi connection reliability

## Current bench service

The existing `benchctl-report.service` now serves the local DC–DC bench
interface on **127.0.0.1:8081**, including the saved `/Runs/` reports. Existing
SSH port forwarding still applies. Each test launched by this service gets a
separate `dcdc-job-*` user service with `Restart=no`; restarting the interface
does not restart or resume acquisition. Measurement deadlines and verified
shutdown remain in the instrument-owning worker. Report generation runs after
shutdown and shares a lock with acquisition.

The earlier static-server unit was saved locally in
`Data/Logs/benchctl-report.service.before-bench-ui-20260927`. See the
[bench guide](../dcdc-bench/docs/bench-ui.md) for the current workflow.

Later inspection found a VS Code file-watch limit error for the entire home
directory. Generated reports, tools and caches are now excluded from those
remote file watches; see [the evidence and applied settings](VS-Code-File-Watching.md).
This reduces unnecessary editor work. It does not prove that every SSH
disconnection had the same cause.

## Temporary disk swap used for report rendering

The 27 September source-limit test finished with both outputs verified OFF.
Subsequent HTML/PDF builds and browser checks needed **768 MiB of extra disk
swap** at `dcdc-bench/test-artifacts/report-render.swap`, alongside existing
zram. The file was ignored by Git and excluded from VS Code file watching. No
boot-time swap configuration was added.

Two cleanup checks that afternoon found insufficient spare RAM to bring the
remaining swapped pages back without increasing memory pressure. At the second
check, about 131.5 MiB remained in that file with only 137.3 MiB RAM available,
so the swap was **left active** at that time.

The host restarted at about 21:28 PDT the same day (see below), which ended the
temporary activation. At about 22:15 PDT, `swapon --show` listed only
`/dev/zram0`, and the inactive swap file was removed. It was recreated for the
evening's multi-agent window and removed again after the 01:07 restart on
28 September (see below). Only the original zram swap remains enabled.

If a future render needs the same headroom, create the file again for that
session only. Do not delete an active swap file; after use, run:

```bash
sudo swapoff ~/rigol-control/dcdc-bench/test-artifacts/report-render.swap && \
  rm ~/rigol-control/dcdc-bench/test-artifacts/report-render.swap
```

## Restart on 28 September at 01:07

A third unclean restart followed at about 01:07 PDT on 28 September while nine
coding agents, the VS Code server and Claude Code shared the host. Just before
it, `free -m` showed 24 MiB available with the 905 MiB zram device and the
768 MiB temporary disk swap both nearly full; the largest residents were the
VS Code server (about 530 MiB resident plus swapped) and Claude Code (about
440 MiB). No bench job was running and no instrument was energized. The
temporary swap file was removed after the reboot, at 07:50 PDT, once
`swapon --show` listed only `/dev/zram0`. Lesson recorded in the coordinator's
notes: on this host run at most two or three agents at once and never render
reports while agents run.

## Restarts observed later on 27 September

`journalctl --list-boots` showed two further boots after the morning
inspection: one beginning at about 18:49 PDT and one at about 21:28 PDT. The
journal for the boot that ended at 21:29 has no shutdown sequence; its last
entries are a Chromium scope started at 21:27:13 and its CPU accounting at
21:29:31. Both the SSH session and the editor session ended at that time. This
is consistent with the earlier unclean restarts and with heavy memory use
while a browser was running, but the retained log does not identify the reset
cause. The bench service restarted at login because lingering is enabled; no
acquisition was in progress.

## What the bench inspection found

Inspection: 27 September 2026, approximately 02:16–02:18 PDT. This is a
diagnostic snapshot of the development Pi, not a guarantee about another host.

| Observation | Interpretation |
| --- | --- |
| Raspberry Pi 3B+, 905 MiB usable RAM; about 150 MiB available at inspection | There is little room for a browser, plotting engine, and document compiler alongside VS Code. |
| About 736 MiB of logical zram swap occupied; compressed storage used about 238 MiB of RAM | Compressed swap is already using part of the same limited physical RAM. It does not provide the equivalent of another physical RAM module. |
| Codex and the VS Code extension host together used about 400–420 MiB resident RAM | Remote development itself is a significant part of the workload. |
| The preceding boot logged an MMC worker blocked for 120, 241, and 362 seconds, followed by SSH authentication and session-release timeouts | The host had a storage/kernel stall. An SSH keepalive setting alone cannot repair this. The log does not identify whether the cause was the SD card, driver, or resource contention. |
| Three boots are retained; the preceding boot has no normal shutdown sequence at its end | Some interruptions involved the Pi restarting. The logs do not establish the reset cause. |
| A 60-second hardware watchdog is enabled; current watchdog boot status is zero | The watchdog is present. These observations do not prove it caused a reset. |
| No OOM kill, undervoltage, or Ethernet link-down event found in the retained kernel logs; current throttle flags were zero and temperature was 50.5 °C | These causes were not demonstrated by the available evidence. Their absence from an incomplete log is not proof they never happened. |
| An earlier boot logged an Ethernet address conflict with the Pi's own Wi-Fi interface; Wi-Fi was subsequently disabled and remains disabled | The simultaneous-interface issue has already been mitigated. Ethernet has stayed connected during the current boot. |
| The report service is enabled and healthy; user lingering was disabled at inspection | The service starts at login and may stop after the final logout. This is separate from the client-side port-forwarding tunnel. |

The kernel is booted with `cgroup_disable=memory`. Do not assume that a
`systemd-run` memory limit protects this host without first enabling and
verifying memory controllers; that configuration change would need a reboot.

During the first extended converter test on the same day, one four-channel
measurement spanned **777.600 ms**. The instrument query calls themselves took
**24.954 ms**; **752.646 ms** elapsed between queries while the worker performed
per-reading persistence. The test correctly stopped at its 750 ms limit and
verified both outputs OFF. This is direct evidence of host-side acquisition
delay, separate from the earlier multi-minute MMC stall. The corrected worker
collects the four readings before fsync, and accepts a cycle only after its raw
records are durable. The electrical and timing limits are unchanged.

## Practical changes

### Keep acquisition lightweight

Run instrument acquisition without a browser or PDF renderer in parallel.
Generate reports after both outputs have been switched off. Use the installed
headless browser and one render at a time. For regular use, generate reports
on a computer with more memory using the saved run data.

Temporary disk swap was used only for serial report generation and verification,
after acquisition had completed. It was removed after the later restart, as
described above; only the original zram swap remains enabled.
Adding permanent SD-card swap is not the first remedy while the retained logs
show an MMC stall. If storage stalls recur under a light workload, back up the
run data and inspect or replace the storage before longer unattended use.

### Keep the report server available after logout

On a dedicated bench Pi, the following reversible setting keeps the user's
enabled services running after logout and starts that user manager at boot:

```sh
sudo loginctl enable-linger <user>
loginctl show-user <user> -p Linger
```

Undo with `sudo loginctl disable-linger <user>`. This affects all enabled
services for that user. It does not keep an SSH tunnel connected. See the
installed `loginctl(1)` manual, `enable-linger`.

Applied on this bench on 27 September 2026 at approximately 02:21 PDT:
`loginctl show-user <user> -p Linger` returned `Linger=yes`, and
`benchctl-report.service` remained active. No reboot or network change was
needed. The client still needs its forwarded port after reconnecting.

### Help the client detect and tolerate brief interruptions

In VS Code on **your computer**, open **Remote–SSH: Open SSH Configuration
File** and add these options to the existing block for the Pi:

```sshconfig
Host <pi-hostname>
    ServerAliveInterval 30
    ServerAliveCountMax 6
```

Use the actual `Host` alias you connect with. The client sends an encrypted
keepalive after 30 seconds without server data and tolerates six unanswered
checks. This can help with idle network timeouts and makes a failed connection
detectable; it cannot keep a powered-off or stalled Pi responsive. These are
client settings, so changing them in the Pi's SSH configuration does not change
the connection from your computer. [OpenSSH client configuration manual](https://man.openbsd.org/ssh_config#ServerAliveInterval).

For saved reports, downloading the HTML/PDF archive eliminates the tunnel
dependency entirely. See [opening reports](Viewing-Local-Reports.md).

## Read-only checks after another interruption

Run these on the Pi after reconnecting:

```sh
uptime
journalctl --list-boots --no-pager
journalctl -k -b -1 --no-pager -n 100
journalctl -k -b --no-pager -n 100
free -h
zramctl
vmstat 1 5
vcgencmd get_throttled
vcgencmd measure_temp
systemctl --user status benchctl-report.service --no-pager
loginctl show-user <user> -p Linger
```

If the boot ID changes, the host restarted. If uptime continues but VS Code
disconnected, correlate the disconnect time with `journalctl -u ssh` and the
client's **Remote–SSH** output. If only the web page fails, check the service
and the forwarded address in VS Code's **Ports** panel first.

Boot timestamps can overlap after clock synchronization; boot IDs and each
boot's monotonic timestamps (`journalctl -b -1 -o short-monotonic`) distinguish
the sequences more reliably.
