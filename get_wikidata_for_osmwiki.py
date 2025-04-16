"""This script requests wikidata on certains properties. The collected data are structured
to feed the following OpenStreetMap Wiki Page : https://wiki.openstreetmap.org/wiki/Module:WikidataCountryInfo
These data can thus be used largely in the wiki.

Update of data requires to run this script and updating wiki module page with the script's output (console or txt file).

Script by ben10dynartio shared under WTFPL licence.
"""

import requests
import pandas as pd
import numpy as np
from urllib.parse import unquote
from datetime import datetime


# URL de l'endpoint SPARQL de Wikidata
SPARQL_URL = "https://query.wikidata.org/sparql"

wikidata_properties = [ # List of properties that will be requested from Wikidata
    # (property name, wikidata property id, has_date, datatype, get_label)
    ("codeiso2", 297, False, str, False),
    ("continent", 30, False, list, True),
    ("area_km2", 2046, False, float, False),
    ("population", 1082, True, int, False),
    ("gdp_bd", 2131, True, float, False),
    ("languages", 37, False, list, True),
    ("flag_image", 41, False, str, False),
    ("locator_map", 242, False, list, False),
    ("osm_rel_id", 402, False, str, False),
]


def fetch_wikidata(query):
    response = requests.get(SPARQL_URL, params={'query': query, 'format': 'json'})
    response.raise_for_status()
    return response.json()


def restructure_json(wikidata_result):
    rows = []
    for item in wikidata_result["results"]["bindings"]:
        dic = {key:val.get("value", "") for key, val in item.items()}
        rows.append(dic)
    return rows


def build_basic_query(properties):
    """Building a query to request a list of basic properties
    (i.e. not dated and not list : if several statement, only first is kept)"""

    # Process label property and build query
    select_string = "".join([f" ?{a[0]}" if not a[4] else f" ?{a[0]}Label" for a in properties])
    optional_string = "\n        ".join(["OPTIONAL { ?country wdt:P%s ?%s. }" % (a[1], a[0]) for a in properties])

    SPARQL_QUERY="""SELECT distinct ?country ?countryLabel ?wikipedia %s WHERE { 
        ?country p:P31 ?country_instance_of_statement .    
        ?country_instance_of_statement ps:P31 wd:Q3624078  .
        ?country ^schema:about ?wikipedia .
        ?wikipedia schema:isPartOf <https://en.wikipedia.org/>; 
        filter not exists{?country p:P31/ps:P31 wd:Q3024240 }  
        %s
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en".}
        }  order by ?countryLabel"""
    SPARQL_QUERY = SPARQL_QUERY % (select_string, optional_string) # replace in query %s
    return SPARQL_QUERY


def build_list_query(property):
    """Building a query to request one attribute in the form of list"""
    property_name = f"?{property[0]}" if not property[4] else f"?{property[0]}Label"

    SPARQL_QUERY="""SELECT distinct ?country ?countryLabel ?codeiso2 %s WHERE { 
        ?country p:P31 ?country_instance_of_statement .    
        ?country_instance_of_statement ps:P31 wd:Q3624078  ;
        filter not exists{?country p:P31/ps:P31 wd:Q3024240 }  
        OPTIONAL { ?country wdt:P%s ?%s. }
        OPTIONAL { ?country wdt:P297 ?codeiso2. }
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en".}
        }  order by ?countryLabel"""
    SPARQL_QUERY = SPARQL_QUERY % (property_name, property[1], property[0]) # replace in query %s
    return SPARQL_QUERY


def build_dated_query(property):
    """Building a query to request one dated attribute in the form of list"""

    SPARQL_QUERY = """SELECT ?country ?%s ?date_%s ?codeiso2 WHERE {
      ?country p:P31 ?country_instance_of_statement .    
        ?country_instance_of_statement ps:P31 wd:Q3624078  ;
        filter not exists{?country p:P31/ps:P31 wd:Q3024240 }  
      OPTIONAL { ?country wdt:P297 ?codeiso2. }
      OPTIONAL {
        ?country p:P%s ?%s_statement.
        ?%s_statement ps:P%s ?%s;
                     pq:P585 ?date_%s.
      }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    ORDER BY ?codeiso2 DESC(?date_%s)
    """
    qreplace = ((property[0],) * 2 + (property[1],) + (property[0],) * 2 + (property[1],) + (property[0],) * 3) # properties to replace %s
    SPARQL_QUERY = SPARQL_QUERY % qreplace
    return SPARQL_QUERY


def restructure_dated_property(rows, nameattribute):
    df = pd.DataFrame(rows).fillna("")
    df = df[df["codeiso2"]!=""]
    df = df.sort_values("date_" + nameattribute, ascending = False)
    df = df.groupby("codeiso2").first().reset_index()
    return {r["codeiso2"]:r[nameattribute] for r in df.to_dict(orient='records')}


def process_lua_data(df, selected_property):
    df = df.sort_values("name")
    list_codes_iso = [f'"{v}"' for v in df["codeiso2"].unique().tolist()]
    mystr = "-- begin data section\n"
    mystr += "data = {\n\n"
    mystr += "    countrylist = {" + ", ".join(list_codes_iso) + "},\n\n"
    for item in selected_property:
        if item != "codeiso2":
            tabitem = [f'{row["codeiso2"]} = "{row[item]}"' for row in df.to_dict(orient='records') if row["codeiso2"]]
            mystr += "    " + item + " = {" + ", ".join(tabitem) + "},\n\n"
    mystr += "}\n\n"
    mystr += f'last_update = \"{datetime.today().strftime("%Y-%m-%d")}\"'
    mystr += "\n-- end data section"
    return mystr


if __name__ == "__main__":
    # request basic properties
    print("-- Requesting basic properties")
    basic_properties = [f for f in wikidata_properties if (not f[2]) and (f[3] != list)] # Exclude dated and list attribute
    q = build_basic_query(basic_properties)
    result = restructure_json(fetch_wikidata(q))
    df = pd.DataFrame(result).fillna("")

    df : pd.DataFrame = df[df["codeiso2"]!=""] # Filtering country with no codeiso2
    df = df.groupby(["codeiso2"]).first().reset_index() # Group by code

    # request list attribute
    print("-- Requesting list properties")
    list_properties = [f for f in wikidata_properties if f[3] == list]
    dfl = {}
    for property in list_properties:
        print("---", property[0])
        q = build_list_query(property)
        result = restructure_json(fetch_wikidata(q))
        dfl[property[0]] : pd.DataFrame = pd.DataFrame(result).fillna("")
        dfl[property[0]] = dfl[property[0]][dfl[property[0]]["codeiso2"]!=""]
        if property[4]: #if it has label
            dfl[property[0]][property[0]] = dfl[property[0]][property[0] + "Label"]

    print("-- Clear list properties")
    # Clean continent name
    dfl["continent"]["continent"] = np.where(dfl["continent"]["continentLabel"].isin(['Insular Oceania', 'Australian continent']),
                                                  "Oceania", dfl["continent"]["continentLabel"])
    dfl["continent"] = dfl["continent"].groupby(["codeiso2"]).first().reset_index()

    # Concatenate languages
    dfl["languages"] = dfl["languages"].groupby(["codeiso2"])['languages'].apply(', '.join).reset_index()

    # Manage locator map
    dfl["locator_map"]["locator_map"] = dfl["locator_map"]["locator_map"].str.replace("http://commons.wikimedia.org/wiki/Special:FilePath/", "").map(unquote)
    dfl["locator_map"]["locator_map_score"] = 99
    locator_map_score_dict = {
        "orthographic":2,
        "orthographic projection":1,
        "on the globe":3
    }
    for key, val in locator_map_score_dict.items():
        dfl["locator_map"]["locator_map_score"] = dfl["locator_map"]["locator_map"].apply(lambda x: locator_map_score_dict.get(x, 99))
    dfl["locator_map"] = dfl["locator_map"].sort_values("locator_map_score")
    dfl["locator_map"] = dfl["locator_map"].groupby(["codeiso2"]).first().reset_index()

    # Structure property as a dict
    conversion_list_dict = {}
    for property in list_properties:
        conversion_list_dict[property[0]] = {r["codeiso2"]:r[property[0]] for r in dfl[property[0]].to_dict(orient='records')}

    ## Request date property
    print("-- Requesting date properties")
    date_properties = [f for f in wikidata_properties if f[2]]
    conversion_date_dict = {}
    for property in date_properties:
        print("---", property[0])
        q = build_dated_query(property)
        result = restructure_json(fetch_wikidata(q))
        # Structure property as a dict
        conversion_date_dict[property[0]] = restructure_dated_property(result, property[0])

    ## Gather all data
    print("-- Gathering data")
    for key, dictval in {**conversion_list_dict, **conversion_date_dict}.items():
        print(" dict ", key, " = ", dictval)
        df[key] = df["codeiso2"].apply(lambda x: dictval.get(x, ""))

    # Export brut data
    df.to_csv("countries_wikidata_brut.csv")

    ## Clean data for rendering
    df["name"] = df["countryLabel"]

    df["area_km2"] = df["area_km2"].astype(float)
    df["area_km2"] = np.where(df["area_km2"] >= 100, df["area_km2"].round(), df["area_km2"])
    df["area_km2"] = df["area_km2"].apply(lambda x: f'{x:,}' if isinstance(x, float) else "")
    df["area_km2"] = np.where(df["area_km2"].str.endswith(".0"),
                              df["area_km2"].str[:-2], df["area_km2"])

    df["population"] = df["population"].apply(lambda x: f'{int(x):,}' if x else "")

    df["gdp_bd"] = df["gdp_bd"].apply(lambda x: "{:.1f}".format(float(x)/1000000000) if x else "")

    df["flag_image"] = df["flag_image"].str.replace(
        "http://commons.wikimedia.org/wiki/Special:FilePath/", "").map(unquote)

    df["wikipedia"] = df["wikipedia"].str.replace("https://en.wikipedia.org/wiki/", "").map(unquote)

    df["wikidata_id"] = df["country"].str.replace("http://www.wikidata.org/entity/", "")

    # Export rendered data
    df.to_csv("countries_wikidata_formated.csv")

    # Build Lua Structure for wiki module and export it
    wikistring = process_lua_data(df, [f[0] for f in wikidata_properties] + ["name", "wikipedia", "wikidata_id"])
    with open("countries_wikidata_lua.txt", "w") as text_file:
        text_file.write(wikistring)

    print(wikistring)
