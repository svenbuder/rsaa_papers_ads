from astropy.table import Table
import numpy as np
import os
import re
import sys
from datetime import datetime
import ads
ads.config.token = os.getenv('ADS_API_TOKEN')

"""
Monthly publications from the Research School of Astronomy and Astrophysics (RSAA) at the Australian National University (ANU) are posted to the RSAA website.
This script queries the ADS database for new publications from RSAA and generates an executive summary of the new publications. The executive summary is saved to a text file.

This script is expected to be run about once a month.

This code is based on the script by Andy Casey at https://github.com/andycasey/ads-paperboy-monash
"""

OUTPUT_PATH_PREFIX = "{here}/lunations/RSAA_Papers_{year}_{month}"
LOCAL_RECORDS_PATH = "{here}/records.csv"
ADS_QUERY = "aff:\"Australian National University\""
EXECUTIVE_SUMMARY_ARTICLE_FORMAT = '{count}. <a href="{formatted_url}">{article.title[0]}</a><br>{formatted_authors}, {article.pub}, {formatted_volume}{formatted_issue}{formatted_page} ({formatted_year}).<br>'

def strip_affiliations(aff):
    aff = aff.replace("&amp;", "&")
    return [ea.replace(",", "").replace(":", "").lower().strip() for ea in aff.split(";")]

def matching_author(author, aff):
    """
    Check if the author is affiliated with the Research School of Astronomy and Astrophysics (RSAA) at the Australian National University (ANU).

    Parameters
    ----------
    author : str
        Author name.
    aff : list of str
        Author affiliations.

    Returns
    -------
    is_matching_author : bool
        True if the author is affiliated with RSAA at ANU.
    meta : list
        If is_matching_author is True, meta contains the index of the matching affiliation, the author name, and the affiliation list.
    """

    stripped_affiliations = strip_affiliations(aff)

    for j, sa in enumerate(stripped_affiliations):
        if ("astronomy" in sa and "2611" in sa):
            return (True, [j, author, aff])

    return (False, [])

def format_author(author, aff):
    """
    Format the author name for display in the executive summary.

    Parameters
    ----------
    author : str
    aff : list of str

    Returns
    -------
    formatted_author : str
    """
    is_matching_author, meta = matching_author(author, aff)
    return f"*{author.upper()}*" if is_matching_author else author


def formatted_summary(article, long_author_list=50):
    """
    Format the article information for display in the executive summary.

    Parameters
    ----------
    article : ads.Article
    long_author_list : int
        Number of authors to display before truncating the author list.

    Returns
    -------
    kwds : dict
        Dictionary of formatted information

    """

    if len(article.author) > long_author_list:
        skip, total_skip = (0, 0)

        authors = []
        for j, (author, aff) in enumerate(zip(article.author, article.aff)):
            if j < 1:
                authors.append(format_author(author, aff))

            else:
                is_matching_author, meta = matching_author(author, aff)

                if is_matching_author:
                    if skip > 0:
                        authors.append("...")
                        skip = 0
                    authors.append(format_author(author, aff))

                else:
                    skip += 1
                    total_skip += 1

        if skip > 0:
            authors.append("et al.")

        formatted_authors = "; ".join(authors) + f" ({total_skip} authors not shown)"

    else:
        formatted_authors = "; ".join([format_author(auth, aff) for auth, aff in zip(article.author, article.aff)])

    # Format the rest of the information.
    kwds = dict(article=article, formatted_authors=formatted_authors,
                formatted_volume="in press" if article.volume is None else article.volume,
                formatted_issue="" if article.issue is None else f", {article.issue}",
                formatted_page=f", {article.page[0]}" if (article.page is not None and article.page[0] is not None) else "",
                formatted_year=article.pubdate.split("-")[0],
                formatted_url='https://ui.adsabs.harvard.edu/abs/'+article.bibcode)

    return kwds

def load_records(path):

    if os.path.exists(path):
        try:
            return Table.read(path, encoding="latin-1")
        except:
            return Table.read(path, encoding="utf-8")

    # Return an empty Table with the expected columns.
    return Table(rows=None,
                 names=('id', 'updated', 'title', 'bibcode', 'pubdate'),
                 dtype=('i4', 'S26', 'S500', 'S100', 'S100'))

def prepare_record(article):
    return (int(article.id), f"{datetime.now()}", str(article.title[0].encode()), article.bibcode, article.pubdate)


if __name__ != "__main__":
    sys.exit()

# Be in the here and now.
now = datetime.now()
here = os.path.dirname(os.path.realpath(__file__))

# Load in the records.
local_records_path = LOCAL_RECORDS_PATH.format(here=here)
records = load_records(local_records_path)

print(records)

# Build the query.
if len(sys.argv) >= 3:
    year, month = map(int, (sys.argv[1:3]))

else:
    year, month = (now.year, now.month - 1)

    if 1 > month:
        year, month = (year - 1, 12)

now = datetime(year, month, 1)
print(now)

print(f"Querying {year} / {month}")

query = f"""
    {ADS_QUERY}
    AND (
            (property:refereed AND pubdate:{year}-{month:02d})
        OR  identifier:\"{year % 100}{month:02d}.*\"
        )
    """

# Clean up whitespace.
query = re.sub("\s{2,}", " ", query).strip()
fields = ["id", "first_author", "author", "aff", "title", "year", "bibcode",
          "identifier", "journal", "volume", "pub", "page", "issue", "pubdate"]

articles = ads.SearchQuery(q=query, fl=fields)

new_articles = []

for i, article in enumerate(articles):

    print(f"Checking article {i} ({article})")

    # Check to see if already posted.
    if int(article.id) in records["id"]:
        print(f"  Skipping article {i} ({article}) because already posted")
        continue

    # Get the matching authors.
    matching_authors = []
    for i, (is_matching_author, meta) \
    in enumerate(map(matching_author, *(article.author, article.aff))):

        if is_matching_author:
            matching_authors.append([i] + meta)

    if len(matching_authors) == 0:
        print(f"  Skipping article ({article}) because no matched authors")
        continue

    # OK, this is new.
    new_articles.append((article, matching_authors))
    records.add_row(prepare_record(article))

print(f"Total number of new articles: {len(new_articles)}")

# Save the records.
records.write(local_records_path, overwrite=True)
print(f"Saved records to {local_records_path}")

if len(new_articles) == 0:
    sys.exit()


# Sort the new records to have first authors at front.
author_index = []
for a, ma in new_articles:
    if len(ma):
        author_index.append(ma[0][0])
    else:
        author_index.append(1000)

na_indices = np.argsort(author_index)
new_articles = [new_articles[idx] for idx in na_indices]

# Create an executive summary of the new records.
executive_summary = []

for count, (article, matching_authors) in enumerate(new_articles, start=1):

    kwds = formatted_summary(article)
    kwds.update(count=count)

    executive_summary.append(EXECUTIVE_SUMMARY_ARTICLE_FORMAT.format(**kwds))

executive_summary = "\n".join(executive_summary)

executive_summary_path = OUTPUT_PATH_PREFIX.format(year=year, month=month, here=here) + ".txt"
with open(executive_summary_path, "w") as fp:
    fp.write(executive_summary)
