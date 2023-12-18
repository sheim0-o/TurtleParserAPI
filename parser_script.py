from flask_cors import CORS
from flask import Flask, request, Response, jsonify

import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

@app.route('/api/py-parse', methods=['POST'])
def submit_data():
    data = {}
    try:
        data_string = request.json.get('json')
        data = json.loads(data_string)
        received_data_from_site = scrape_game_data(data.get("url"), data.get("pageParams"), data.get("elementsContainer"), data.get("searchedElement"))

        # Возвращаем успешный ответ
        return jsonify({'status': 'success', 'message': 'Data submitted successfully', 'result': received_data_from_site})
    except Exception as e:
        # В случае ошибки возвращаем соответствующий ответ
        return jsonify({'status': 'error', 'message': str(e)})




# Словарь типов поиска
search_type_mapping = {
    "SearchByTag": lambda parent_element, name: parent_element.find(name),
    "SearchByTagAll": lambda parent_element, name: parent_element.find_all(name, recursive=False),
    "SearchById": lambda parent_element, name: parent_element.find(id=name),
    "SearchByIdAll": lambda parent_element, name: parent_element.find_all(id=name, recursive=False),
    "SearchByClass": lambda parent_element, name: parent_element.find(class_=name),
    "SearchByClassAll": lambda parent_element, name: parent_element.find_all(class_=name, recursive=False),
}

# Словарь типов информации
info_type_mapping = {
    "InnerText": lambda element, attr: element.get_text(strip=True),
    "FromAttribute": lambda element, attr: element.get(attr, ""),
}

def modify_url(original_url, parameter_name, parameter_new_value):
    parsed_url = urlparse(original_url)
    query_params = parse_qs(parsed_url.query)
    query_params[parameter_name] = [str(parameter_new_value)]
    updated_query = urlencode(query_params, doseq=True)
    updated_url = parsed_url._replace(query=updated_query).geturl()
    return updated_url


def scrape_game_data(url, page_params, elements_container, searched_element):
    columns = []
    get_elements_container = search_type_mapping.get(elements_container["typeOfSearchElement"])
    get_serched_element_in_container = search_type_mapping.get(searched_element["typeOfSearchElement"]+"All")

    if page_params.get("isMultiplePages"):
        name_of_page_param = page_params.get("nameOfPageParam")
        first_page = page_params.get("firstPage")
        step = page_params.get("step")
        last_page = page_params.get("lastPage")


        for page in range(first_page, last_page + 1, step):
            current_url = modify_url(url, name_of_page_param, page)
            columns.append(get_page_from_url(current_url, elements_container, searched_element, get_elements_container, get_serched_element_in_container))
    else:
        columns.append(get_page_from_url(url, elements_container, searched_element, get_elements_container, get_serched_element_in_container))

    return columns


def get_page_from_url(url, elements_container, searched_element, get_elements_container, get_serched_element_in_container):
    columns = []
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    soup_container = get_elements_container(soup, elements_container["nameOfType"])
    if soup_container is None:
        return []
    soup_searched_element = get_serched_element_in_container(soup_container, searched_element["nameOfType"])
    if soup_searched_element is None:
        return []

    for soup_element in soup_searched_element:
        result = process_element(soup_element, searched_element)
        columns.append(result)
    return columns


def process_element(soup_searched_element, searched_element):
    result = {}

    for searched_info in searched_element["searchedInfo"]:
        result.update(save_info(soup_searched_element, searched_info))

    for el in searched_element["searchedElements"]:
        get_child_serched_element = search_type_mapping.get(el["typeOfSearchElement"])
        soup_el = get_child_serched_element(soup_searched_element, el["nameOfType"])
        if soup_el is None:
            continue
        received_data = process_element(soup_el, el)
        if(received_data != {}):
            result.update(received_data)

    return result


def save_info(soup_element, info):
    target_column = info.get("targetColumn")
    type_of_info = info.get("typeOfSearchedInfoPlace")
    attribute_name = info.get("attributeName")

    get_info_from_element = info_type_mapping.get(type_of_info)
    searched_info = get_info_from_element(soup_element, attribute_name)

    if isinstance(searched_info, list):
        searched_info = ', '.join(map(str, searched_info))

    if searched_info is None:
        return {target_column: ""}
    else:
        return {target_column: searched_info}





if __name__ == '__main__':
    app.run(debug=True)
