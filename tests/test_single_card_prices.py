from scraper import parse_single_card_prices


SAMPLE_HTML_NO_TABLE_WRAPPER = """
<div class="table-header d-none d-lg-flex"></div>
<div class="table-body">
  <div class="article-row">
    <div class="article-condition"><span class="badge">NM</span></div>
    <div class="product-attributes">
      <span data-bs-original-title="English"></span>
    </div>
    <div class="col-offer"><span class="color-primary">75,00 €</span></div>
  </div>
  <div class="article-row">
    <div class="article-condition"><span class="badge">NM</span></div>
    <div class="product-attributes">
      <span data-bs-original-title="English"></span>
    </div>
    <div class="col-offer"><span class="color-primary">80,00 €</span></div>
  </div>
</div>
"""


def test_parse_single_card_prices_falls_back_to_article_rows():
    prices = parse_single_card_prices(SAMPLE_HTML_NO_TABLE_WRAPPER, "English")
    assert prices == [75.0, 80.0]
