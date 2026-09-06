import unittest

import import_morphhb as imp


class ImportMorphHBTests(unittest.TestCase):
    def test_form_normalization_keeps_niqqud_but_removes_accents_and_meteg(self):
        source = "וַיִּשְׁלַ֨ח"
        normalized = imp.normalize_form(source)
        self.assertNotIn("֨", normalized)
        self.assertIn("ַ", normalized)
        self.assertIn("ִ", normalized)
        self.assertEqual(normalized, imp.normalize_form("וַיִּשְׁלַח"))

    def test_consonantal_normalization_removes_points(self):
        self.assertEqual(imp.normalize_consonantal("וַיִּשְׁלַ֨ח"), "וישלח")

    def test_prefix_plus_qal_wayyiqtol_selects_verb_as_main_segment(self):
        segments, main = imp.parse_morphology("HC/Vqw3ms")
        self.assertEqual(len(segments), 2)
        self.assertIsNotNone(main)
        self.assertEqual(main.pos_code, "V")
        self.assertEqual(main.verb_stem_code, "q")
        self.assertEqual(main.verb_conjugation_code, "w")
        self.assertEqual(main.person_code, "3")
        self.assertEqual(main.gender_code, "m")
        self.assertEqual(main.number_code, "s")

    def test_primary_lemma_aligns_to_lexical_core(self):
        components, primary = imp.parse_lemmas("c/7971", 2)
        self.assertEqual(primary, 7971)
        self.assertFalse(components[0].is_primary)
        self.assertTrue(components[1].is_primary)

    def test_synthetic_genesis_32_4_round_trip(self):
        verse_map_xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <verseMap><verse wlc='Gen.32.4' kjv='Gen.32.3' type='full'/></verseMap>
        """
        gen_xml = """<?xml version='1.0' encoding='UTF-8'?>
        <osis xmlns='http://www.bibletechnologies.net/2003/OSIS/namespace'>
          <osisText>
            <div type='book' osisID='Gen'>
              <chapter osisID='Gen.32'>
                <verse osisID='Gen.32.4'>
                  <w lemma='7971' morph='HVqw3ms'>וַ/יִּשְׁלַח</w>
                  <w lemma='3290' morph='HNpmsa'>יַעֲקֹב</w>
                </verse>
              </chapter>
            </div>
          </osisText>
        </osis>
        """.encode("utf-8")

        mapping = imp.parse_verse_map(verse_map_xml)
        verses = imp.parse_book(gen_xml, mapping)
        self.assertEqual(len(verses), 1)
        verse = verses[0]
        self.assertEqual(verse.osis_wlc, "Gen.32.4")
        self.assertEqual(verse.osis_kjv, "Gen.32.3")
        self.assertEqual(verse.chapter_kjv, 32)
        self.assertEqual(verse.verse_kjv, 3)

        target = imp.verify_050(verses)
        self.assertEqual(target.primary_strong, 7971)
        self.assertEqual(target.main_stem_code, "q")
        self.assertEqual(target.main_conjugation_code, "w")
        self.assertEqual(target.surface, "וַיִּשְׁלַח")


if __name__ == "__main__":
    unittest.main()
