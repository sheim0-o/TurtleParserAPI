from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from http import HTTPStatus
from pydantic import BaseModel
import json
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode
import os
API_KEY = os.environ.get('API_KEY')

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

class RequestedData(BaseModel):
    json: str
    api_key: str

@app.post("/api/parser")
def handle_request(requestedData: RequestedData):
    api_key = requestedData.api_key
    requested_json = requestedData.json
    
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="You don't have access to this method!")
        
    form = {}
    result_data = {}
    try:
        form = json.loads(requested_json)
        result_data = scrape_game_data(form["url"], form["pageParams"], form["elementsContainer"], form["searchedElement"])
        if result_data["status"] == "success":
            pdTable = pd.DataFrame(result_data["columns"])
            temp_csv_filename = 'temp_csv_file.csv'
            pdTable.to_csv(temp_csv_filename, index=False)
        
            with open(temp_csv_filename, 'r', encoding='utf-8') as file:
                csv_content = file.read()
            os.remove(temp_csv_filename)
            compressed_csv_content = gzip.compress(csv_content.encode('utf-8'))
            
            headers = {
                'Content-Disposition': 'attachment; filename=result.csv.gz', 
                'Content-Encoding': 'gzip',
                'Cache-Control': 'no-store',
            }            
            return StreamingResponse(iter([compressed_csv_content]), headers=headers)
        elif result_data["status"] == "error":
            raise HTTPException(status_code=400, detail={"form":form, "result_data":result_data, "errors": result_data["errors"] })
        else:
            raise HTTPException(status_code=404, detail={"form":form, "result_data":result_data, "error": "Data wasn't received"})
    except Exception as e:
        error_status_code = getattr(HTTPStatus, str(e), 400)
        raise HTTPException(status_code=error_status_code, detail={"form":form, "result_data":result_data, "error":str(e)})



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
    result = {"status":"", "columns":[], "errors":[]}
    get_elements_container = search_type_mapping.get(elements_container["typeOfSearchElement"])
    get_serched_element_in_container = search_type_mapping.get(searched_element["typeOfSearchElement"]+"All")

    if page_params["isMultiplePages"]:
        name_of_page_param = page_params["nameOfPageParam"]
        first_page = page_params["firstPage"]
        step = page_params["step"]
        last_page = page_params["lastPage"]


        for page in range(first_page, last_page + 1, step):
            current_url = modify_url(url, name_of_page_param, page)
            result_of_parsing_page = get_page_from_url(current_url, elements_container, searched_element, get_elements_container, get_serched_element_in_container)
            if len(result_of_parsing_page["columns"]) > 0:
                result["columns"].append(result_of_parsing_page["columns"])
            if len(result_of_parsing_page["errors"]) > 0:
                result["errors"].append(result_of_parsing_page["errors"])
    else:
        result_of_parsing_page = get_page_from_url(url, elements_container, searched_element, get_elements_container, get_serched_element_in_container)
        if result_of_parsing_page["status"] == "success":
            result["columns"].append(result_of_parsing_page["result_array"])
        elif result_of_parsing_page["status"] == "error":
            result["errors"].append(result_of_parsing_page["result_array"])
    
    if len(result["columns"]) > 0:
        result["status"] = "success"
    elif len(result["errors"]) > 0:
        result["status"] = "error"
    else:
        result["status"] = "no data"
    return result


def get_page_from_url(url, elements_container, searched_element, get_elements_container, get_serched_element_in_container):
    columns = []

    elements_container_type_name = elements_container["nameOfType"]
    searched_element_type_name = searched_element["nameOfType"]
    
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    soup_container = get_elements_container(soup, elements_container_type_name)
    if soup_container is None:
        return {"status":"error", "result_array":{"url":url, "error": f"Container with type '{elements_container_type_name}' wasn't found!"}}
    soup_searched_element = get_serched_element_in_container(soup_container, searched_element_type_name)
    if soup_searched_element is None:
        return {"status":"error", "result_array":{"url":url, "error": f"Searched element with type '{searched_element_type_name}' wasn't found!"}}

    for soup_element in soup_searched_element:
        result = process_element(soup_element, searched_element)
        columns.append(result)
    return {"status":"success", "result_array":columns}


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
    target_column = info["targetColumn"]
    type_of_info = info["typeOfSearchedInfoPlace"]
    attribute_name = info["attributeName"]

    get_info_from_element = info_type_mapping.get(type_of_info)
    searched_info = get_info_from_element(soup_element, attribute_name)

    if isinstance(searched_info, list):
        searched_info = ', '.join(map(str, searched_info))

    if searched_info is None:
        return {target_column: ""}
    else:
        return {target_column: searched_info}
