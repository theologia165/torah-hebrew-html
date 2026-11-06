"""Regression for 086's real Notion query-value percent-encoding."""
import copy
import unittest
from deliver import rt, verify, source_block

class CitationReadbackTests(unittest.TestCase):
    def block(self,url):
        return {'type':'paragraph','paragraph':{'rich_text':rt('参照：モーセの生涯',url)}}

    def test_internal_json11_is_not_a_public_citation(self):
        urls = [
            'https://github.com/theologia165/torah-hebrew-html/blob/asaichi-torah-ver3/ver3/runs/093/json1.1.json',
            'https://raw.githubusercontent.com/theologia165/torah-hebrew-html/asaichi-torah-ver3/ver3/runs/093/json1.1.json?download=1',
            'https://github.com/theologia165/torah-hebrew-html/blob/main/json1%2E1.json#L1',
        ]
        for url in urls:
            with self.subTest(url=url):
                b = source_block([{'label': '本文の参照名', 'url': url}])
                item = b['paragraph']['rich_text'][1]['text']
                self.assertEqual(item['content'], '本文の参照名')
                self.assertNotIn('link', item)

    def test_external_scholarly_citations_remain_linked(self):
        url = 'https://www.newadvent.org/fathers/130103.htm'
        b = source_block([
            {'label': '内部の本文', 'url': 'https://example.org/json1.1.json'},
            {'label': 'Augustine', 'url': url},
        ])
        links = [x['text']['link']['url'] for x in b['paragraph']['rich_text'] if 'link' in x['text']]
        self.assertEqual(links, [url])

    def test_notion_encoded_query_value(self):
        before='https://catholiclibrary.org/library/view?chunk.id=00000027&docId=Fathers-Synchronized-EN/Gregory_of_Nyssa__De_vita_Mosis.en.html'
        after=before.replace('EN/Gregory','EN%2FGregory')
        verify([self.block(before)],[self.block(after)],'unused')

    def test_encoded_data_is_not_a_query_delimiter(self):
        pairs=[
            ('https://example.org/view?doc=a%26mode%3Db','https://example.org/view?doc=a&mode=b'),
            ('https://example.org/a%2Fb?x=1','https://example.org/a/b?x=1'),
            ('https://example.org/view?x=1&x=1','https://example.org/view?x=1'),
            ('https://example.org/view?x=1&y=2','https://example.org/view?y=2&x=1'),
            ('https://example.org/view?x=1','https://elsewhere.org/view?x=1'),
            ('https://example.org/view?x=1#part','https://example.org/view?x=1'),
        ]
        for before,after in pairs:
            with self.subTest(before=before,after=after), self.assertRaisesRegex(AssertionError,'Citation links differ'):
                verify([self.block(before)],[self.block(after)],'unused')

    def test_missing_or_changed_link_fails(self):
        expected=self.block('https://example.org/view?doc=1')
        missing=copy.deepcopy(expected)
        missing['paragraph']['rich_text'][0]['text'].pop('link')
        for actual in (missing,self.block('https://example.org/view?doc=2')):
            with self.assertRaisesRegex(AssertionError,'Citation links differ'):
                verify([expected],[actual],'unused')

if __name__=='__main__':
    unittest.main()
