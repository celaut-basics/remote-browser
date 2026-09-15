# What each architecture needs, and two things none of them can express

Each service directory has its own `NODE-REQUIREMENTS.md`; this is the index, plus
the findings that belong to no single one of them.

| | from the node | from the host |
|---|---|---|
| [`vnc/`](vnc/NODE-REQUIREMENTS.md) | **nothing** | any VNC viewer; reach it through `nodo tunnel`, because RFB's password is eight bytes |
| [`waypipe/`](waypipe/NODE-REQUIREMENTS.md) | [`nodo display`](https://github.com/celaut-project/nodo/issues/367), or nothing and three commands | a Wayland session, `waypipe`, `socat` |
| [`stream/`](stream/NODE-REQUIREMENTS.md) | `CONFIG_INPUT=y` + `CONFIG_INPUT_UINPUT=y`, **or it is view-only** | Moonlight installed natively, and eight tunnels |

Read together they say something the individual files do not: the only architecture
that needs a **capability** is the GameStream one, and it needs it for input rather
than for pixels. The other two need either a convenience (`nodo display`) or
nothing at all.

## What none of them can express

Two gaps found while building these, both about the specification language rather
than about any one service. Neither blocks anything here — one service has no
ancestor chain and none of the three has a parent — but both are what *would* have
blocked the two-service design this repository started as.

### 1. A network grant a parent passes down without holding

`Service.Network` is authorised by intersection up the ancestor chain: a child may
use a domain only if its father declared it, and its father's father, to the top.
The AND is right. What is missing is that one declaration does two jobs at once:

- it **grants** the domain to everything this instance launches, and
- it **takes** the domain for this instance's own VM.

There is no way to write the first without the second. This repository hit it head
on while it was two services: a light parent whose job was to hold a password had
to declare `["*"]`, because its child was a browser — so the node duly wrote
`allow_all_egress_rule` for the parent too, and the manifest an operator reads
before admitting a launch said the control plane might reach the entire internet.
It might. It did not. Nothing in the specification could tell those apart.

And the failure mode is silent in the other direction: a parent that under-declares
gets no error at all. `filter_networks_with_ancestors` returns an empty list,
`build_network_resolution` raises nothing, and the guest boots with the default
`block_all` and no allow rules — a browser that loads no page and reports no
problem, with every symptom in the child and the fix in the parent's manifest.

A `grant_only` flag on the network entry is the smallest thing that separates the
two jobs. The documentation half of this is
[celaut-project/nodo#365](https://github.com/celaut-project/nodo/pull/365).

### 2. "Run me on the node of whoever asked"

Nothing lets a service declare it. Shares force colocation with a **parent**
(`service_requires_parent_colocation`); nothing forces colocation with the
**requester**. Any design where a light service faces the user directly — which is
what a display client is — needs exactly that, and today gets it only by accident,
for as long as `DELEGATE_EXECUTION` happens not to send it somewhere else.

It stopped mattering here when the client stopped being a service. It will matter
again for anything shaped the same way.

## What is deliberately not asked for

**A GPU.** `celaut.Sysresources` is `blkio_weight`, `cpu_period`, `cpu_quota`,
`mem_limit` and `disk_space` — no accelerator field, and no way to declare that an
instance needs one. A service that needs one cannot be scheduled anywhere on this
network, so all three of these are built not to: Chromium rasterises in software
everywhere, `stream/` encodes with x264, `vnc/` with RFB's own encodings, and
`waypipe/` does not encode at all.

**Sound.** `# CONFIG_SOUND is not set` and that is fine. PulseAudio's
`module-null-sink` opens no device — it is arithmetic on a buffer — and its
monitor is a capture source as far as an encoder cares. `stream/` uses exactly
that. The other two have no audio for reasons of their own protocols, not of the
kernel.

**virtio-gpu**, which was considered at length and dropped. `TODO.md` has why.
