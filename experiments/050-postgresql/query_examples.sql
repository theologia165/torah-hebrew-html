-- SQL equivalents of the current 050 search UI.
-- MorphHB codes used here:
--   q = Qal stem
--   w = sequential imperfect / wayyiqtol

-- 1) Same lemma (Strong H7971 / שׁלח) across the Hebrew Bible.
SELECT *
FROM dtworks.search_tokens
WHERE primary_strong = 7971
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 2) Same Form. :form_search is prepared by the importer after removing
-- cantillation/meteg while retaining niqqud.
SELECT *
FROM dtworks.search_tokens
WHERE form_search = :form_search
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 3) Qal only, no lemma restriction.
SELECT *
FROM dtworks.search_tokens
WHERE main_pos_code = 'V'
  AND main_stem_code = 'q'
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 4) wayyiqtol only, no lemma restriction.
SELECT *
FROM dtworks.search_tokens
WHERE main_pos_code = 'V'
  AND main_conjugation_code = 'w'
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 5) Qal + wayyiqtol, all lemmas.
SELECT *
FROM dtworks.search_tokens
WHERE main_pos_code = 'V'
  AND main_stem_code = 'q'
  AND main_conjugation_code = 'w'
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 6) Same lemma + Qal + wayyiqtol.
SELECT *
FROM dtworks.search_tokens
WHERE primary_strong = 7971
  AND main_pos_code = 'V'
  AND main_stem_code = 'q'
  AND main_conjugation_code = 'w'
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 7) Same lemma + Qal + wayyiqtol, Torah only.
SELECT *
FROM dtworks.search_tokens
WHERE primary_strong = 7971
  AND main_pos_code = 'V'
  AND main_stem_code = 'q'
  AND main_conjugation_code = 'w'
  AND tanakh_group = 'torah'
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 8) Same lemma, current book only (Genesis).
SELECT *
FROM dtworks.search_tokens
WHERE primary_strong = 7971
  AND book = 'Gen'
ORDER BY chapter_wlc, verse_wlc, token_index;

-- 9) Custom book selection. FastAPI will bind an array such as
-- ARRAY['Gen','Exod','Deut'].
SELECT *
FROM dtworks.search_tokens
WHERE primary_strong = 7971
  AND book = ANY(:book_codes)
ORDER BY canonical_order, chapter_wlc, verse_wlc, token_index;

-- 10) Future: search a lemma component even when it is not the token's
-- primary lexeme. This uses the normalized token_lemmas table.
SELECT st.*
FROM dtworks.search_tokens st
JOIN dtworks.token_lemmas tl ON tl.token_id = st.token_id
WHERE tl.strong_number = 7971
ORDER BY st.canonical_order, st.chapter_wlc, st.verse_wlc, st.token_index;
