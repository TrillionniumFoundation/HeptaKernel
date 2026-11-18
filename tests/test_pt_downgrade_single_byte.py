#!/usr/bin/env python3
"""Regression guard for actual HIA PTE permission writes, not a concurrency proof.

The independent native differential oracles, dishonest candidates and QEMU
hardware #PF experiments are separately required. This check catches accidental
reintroduction of eight consecutive stores to a live leaf for a one-bit
permission transition, and checks that the exact-old compare still dominates it.
"""
from __future__ import annotations

from pathlib import Path
import unittest

SOURCES = {
    "x86_pt_write_protect": "low",
    "x86_pt_user_revoke": "low",
    "x86_pt_nx_protect": "high",
}


class StoreShapeRejected(ValueError):
    pass


def block_body(source: str, name: str) -> str:
    key = "\nblock " + name + "("
    if source.count(key) != 1:
        raise StoreShapeRejected("expected exactly one " + name + " block")
    tail = source.split(key, 1)[1]
    return tail.split("\nblock ", 1)[0].split("\nend\n", 1)[0]


def verify_source(source: str, mode: str) -> None:
    if mode not in {"low", "high"}:
        raise StoreShapeRejected("unknown permission-bit location")
    compare = block_body(source, "compare_old")
    commit = block_body(source, "commit")
    if ('pc_equal:bool = compare.eq(pc_seen,pc_compare_expected)' not in compare or
            'branch pc_equal commit(' not in compare or
            ' mismatch(' not in compare):
        raise StoreShapeRejected("exact-old compare and refusal must dominate commit")
    if ('{"function":"write_table_u64"}' in commit or
            commit.count("buffer.store(") != 1 or
            commit.count('{"function":"write_reply"}') != 1):
        raise StoreShapeRejected("live PTE must receive only one HIA byte store")
    if "  ret(pc_commit_result)" not in commit:
        raise StoreShapeRejected("missing normal return after acknowledged update")
    if mode == "low":
        required = (
            'pc_commit_byte:u8 = int.cast(pc_commit_new) {"mode":"wrap"}',
            'buffer.store(pc_commit_page,pc_commit_offset,pc_commit_byte)',
        )
        forbidden = ("pc_commit_high", "pc_commit_at", "pc_commit_shift")
    else:
        required = (
            'pc_commit_shift:u64 = const() {"value":56}',
            "pc_commit_high:u64 = int.shr.checked(pc_commit_new,pc_commit_shift)",
            'pc_commit_byte:u8 = int.cast(pc_commit_high) {"mode":"wrap"}',
            'pc_commit_high_offset:usize = const() {"value":7}',
            "pc_commit_at:usize = int.add.wrap(pc_commit_offset,pc_commit_high_offset)",
            "buffer.store(pc_commit_page,pc_commit_at,pc_commit_byte)",
        )
        forbidden = ("buffer.store(pc_commit_page,pc_commit_offset,pc_commit_byte)",)
    if any(fragment not in commit for fragment in required):
        raise StoreShapeRejected("wrong source byte, byte offset or shift")
    if any(fragment in commit for fragment in forbidden):
        raise StoreShapeRejected("wrong physical PTE byte selected")


class HiaPermissionStoreTests(unittest.TestCase):
    def test_all_three_genuine_sources(self) -> None:
        for stem, mode in SOURCES.items():
            with self.subTest(source=stem):
                verify_source(Path("src", stem + ".hepta").read_text(), mode)

    def test_hostile_regressions_are_rejected(self) -> None:
        for stem, mode in SOURCES.items():
            original = Path("src", stem + ".hepta").read_text()
            commit = block_body(original, "commit")
            mutations = [
                commit.replace("buffer.store(", "buffer.load(", 1),
                commit.replace(
                    '  ret(pc_commit_result)',
                    '  pc_extra:u32 = call(pc_commit_page,pc_commit_offset,pc_commit_new) {"function":"write_table_u64"}\n  ret(pc_commit_result)',
                ),
                commit.replace('{"function":"write_reply"}', '{"function":"write_table_u64"}'),
            ]
            if mode == "low":
                mutations.append(commit.replace(
                    "buffer.store(pc_commit_page,pc_commit_offset,pc_commit_byte)",
                    "buffer.store(pc_commit_page,pc_commit_new,pc_commit_byte)",
                ))
                mutations.append(commit.replace(
                    "int.cast(pc_commit_new)", "int.cast(pc_commit_offset)"))
            else:
                mutations.append(commit.replace('{"value":56}', '{"value":48}'))
                mutations.append(commit.replace('{"value":7}', '{"value":6}'))
                mutations.append(commit.replace(
                    "buffer.store(pc_commit_page,pc_commit_at,pc_commit_byte)",
                    "buffer.store(pc_commit_page,pc_commit_offset,pc_commit_byte)",
                ))
            for index, mutant in enumerate(mutations):
                with self.subTest(source=stem, mutation=index):
                    self.assertNotEqual(mutant, commit)
                    # Only mutate the commit: the prior exact-old compare is retained.
                    self.assertEqual(original.count(commit), 1)
                    with self.assertRaises(StoreShapeRejected):
                        verify_source(original.replace(commit, mutant), mode)

    def test_removing_old_value_refusal_is_detected(self) -> None:
        for stem, mode in SOURCES.items():
            source = Path("src", stem + ".hepta").read_text()
            broken = source.replace(
                "branch pc_equal commit(", "branch pc_equal mismatch(", 1)
            self.assertNotEqual(source, broken)
            with self.subTest(source=stem):
                with self.assertRaises(StoreShapeRejected):
                    verify_source(broken, mode)


if __name__ == "__main__":
    unittest.main()
