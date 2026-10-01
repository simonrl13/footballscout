from scout.text.wikipedia import UA, strip_wikitext

WT = """{{Infobox football biography
| name = Harry Kane | clubs1 = [[Tottenham Hotspur F.C.|Tottenham]] {{small|(loan)}}
}}
'''Harry Edward Kane''' is an English [[association football|footballer]].<ref name="a">{{cite web|url=x}}</ref>

==Club career==
On 13 January 2017, Kane signed a new contract with [[Tottenham Hotspur F.C.|Tottenham]] until 2022.<ref>x</ref>
{| class="wikitable"
|-
| 2016–17 || 30 || 29
|}
[[File:Kane.jpg|thumb|Kane in [[2018]]]]
<!-- hidden comment -->
* He suffered an ankle injury in March 2017, ruling him out for six weeks.[https://example.org source]
[[Category:Tottenham Hotspur F.C. players]]
"""


def test_strip_wikitext_keeps_prose_and_drops_markup():
    t = strip_wikitext(WT)
    assert "Harry Edward Kane is an English footballer." in t
    assert "On 13 January 2017, Kane signed a new contract with Tottenham until 2022." in t
    assert "He suffered an ankle injury in March 2017, ruling him out for six weeks." in t
    for junk in ["Infobox", "cite web", "wikitable", "2016–17", "Kane.jpg", "hidden comment", "Category", "<ref", "[[", "{{", "'''"]:
        assert junk not in t, junk


def test_user_agent_identifies_tool_and_contact():
    assert "Bot" in UA and "github.com/simonrl13/footballscout" in UA
