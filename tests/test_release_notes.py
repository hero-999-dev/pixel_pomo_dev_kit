"""A release's text: what changed, then how to install — and the kit's UPDATE
panel showing only the first of those."""
import unittest

import release_notes
from dev_kit import updater
from dev_kit.version import VERSION

CHANGES = """# What changed

## v0.2.0

- Something new.
- And another thing.

## v0.1.9

- An older thing.
"""


class ReleaseText(unittest.TestCase):
    def test_a_version_gets_its_own_lines_and_no_one_elses(self):
        self.assertEqual(release_notes.changes("v0.2.0", CHANGES),
                         "- Something new.\n- And another thing.")
        self.assertEqual(release_notes.changes("0.1.9", CHANGES), "- An older thing.")
        self.assertEqual(release_notes.changes("v0.1", CHANGES), "")
        self.assertEqual(release_notes.changes("v9.9.9", CHANGES), "")

    def test_the_version_being_built_has_something_written_for_it(self):
        # the release workflow would otherwise publish a page that opens on
        # the install guide, and UPDATE would have nothing to say
        self.assertTrue(release_notes.changes(VERSION),
                        f"CHANGES.md has no '## v{VERSION}'")

    def test_what_changed_comes_first_and_the_install_guide_whole_after_it(self):
        text = release_notes.notes("v" + VERSION)
        self.assertTrue(text.startswith(f"## What is new in v{VERSION}\n"))
        news, guide = text.split(release_notes.DIVIDER)
        self.assertIn(release_notes.changes(VERSION), news)
        self.assertIn("## Install on a Mac", guide)
        self.assertIn("## Install on Windows", guide)
        self.assertNotIn("## Install on", news)

    def test_a_version_nobody_wrote_about_still_gets_the_guide(self):
        text = release_notes.notes("v9.9.9")
        self.assertTrue(text.startswith(release_notes.DIVIDER))
        self.assertIn("## Install on Windows", text)


class WhatTheUpdatePanelShows(unittest.TestCase):
    def test_only_what_changed_and_in_plain_words(self):
        shown = updater.whats_new(release_notes.notes("v" + VERSION))
        self.assertTrue(shown)
        self.assertNotIn("Install on", shown)
        self.assertNotIn("curl", shown)
        self.assertNotIn("What is new in", shown)   # the panel has its own heading
        self.assertNotIn("**", shown)
        self.assertNotIn("<!--", shown)

    def test_a_release_written_before_the_divider_shows_no_install_guide(self):
        old = "## Install on a Mac\n\nOpen Terminal...\n\n## Install on Windows\n\n..."
        self.assertEqual(updater.whats_new(old), "")
        self.assertEqual(updater.whats_new("Fixed.\n\n## Install on a Mac\n\n..."), "Fixed.")

    def test_a_release_with_only_a_few_words_shows_them(self):
        self.assertEqual(updater.whats_new("Fixed a thing."), "Fixed a thing.")
        self.assertEqual(updater.whats_new(None), "")
        self.assertEqual(updater.whats_new(""), "")

    def test_the_release_the_kit_reads_carries_it(self):
        release = updater.Release({"tag_name": "v9.0.0",
                                   "body": release_notes.notes("v" + VERSION)})
        self.assertEqual(release.notes, updater.whats_new(release_notes.notes("v" + VERSION)))


if __name__ == "__main__":
    unittest.main()
