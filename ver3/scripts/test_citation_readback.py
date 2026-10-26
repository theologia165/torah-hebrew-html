"""Regression for 086's real Notion query-value percent-encoding."""
import copy
import unittest
from deliver import rt, verify

class CitationReadbackTests(unittest.TestCase):
    def block(self,url):
        return {'type':'paragraph','paragraph':{'rich_text':rt('参照：モーセの生涯',url)}}

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
