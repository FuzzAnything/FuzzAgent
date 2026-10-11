from typing import List
from bs4 import BeautifulSoup
from dataclasses import dataclass


@dataclass
class TableCell:
    text: str

    def add(self, cell: 'TableCell'):
        reached, total = self.parse_value()
        reached2, total2 = cell.parse_value()
        reached += reached2
        total += total2
        self.text = f"{reached/total*100:.2f}% ({reached}/{total})"
    
    def parse_value(self) -> tuple[int, int]:
        if self.text == "00.00% (0/0)":
            return 0, 0
        value = self.text.split("(")[1].split(")")[0]
        reached, total = value.split("/")
        return int(reached), int(total)

@dataclass
class TableRow:
    cells: List[TableCell]

    def reset(self):
        for i in range(len(self.cells)):
            if i == 0:
                continue
            self.cells[i].text = "00.00% (0/0)"

    def sum(self, rows: List['TableRow']):
        self.reset()
        for row in rows:
            for i in range(len(row.cells)):
                if i == 0:
                    continue
                self.cells[i].add(row.cells[i])

@dataclass
class HtmlTable:
    headers: List[str]
    rows: List[TableRow]
    footers: List[TableRow] = None

    def display(self):
        header = "| {} |\n".format(" | ".join(self.headers))
        seg = "|" + ":------|" * len(self.headers) + "\n"
        body = ""
        for row in self.rows:
            cells = [cell.text for cell in row.cells]
            row_text = " | ".join(cells)
            body += row_text
            body += "\n"
        for row in self.footers:
            cells = [cell.text for cell in row.cells]
            row_text = " | ".join(cells)
            body += row_text
            body += "\n"
        msg = header + seg + body
        print(msg)

    def get_locations(self) -> List[str]:
        locations = []
        for row in self.rows:
            location = row.cells[0].text
            locations.append(location)
        return locations

    def compute_total(self):
        if len(self.footers) != 1:
            raise Exception("[!] Error: The footer of the table is not correct!")
        self.footers[0].sum(self.rows)

    def parse_from_html(self, html_content: str):
        """
        Parse the table in HTML and return an HtmlTable object
        
        :param html_content: HTML string
        :return: HtmlTable object
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        table = soup.find('table')
        
        # Parse table header
        headers = []
        thead = table.find('thead')
        if thead:
            header_row = thead.find('tr')
            if header_row:
                for th in header_row.find_all('th'):
                    headers.append(th.get_text(strip=True))
        
        # Parse table body
        rows = []
        tbody = table.find('tbody')
        if tbody:
            for tr in tbody.find_all('tr'):
                cells = []
                for td in tr.find_all('td'):
                    # Get cell text
                    text = td.get_text(strip=True)
                    cells.append(TableCell(text=text))
                rows.append(TableRow(cells))
        
        # Parse table footer
        footers = []
        tfoot = table.find('tfoot')
        if tfoot:
            for tr in tfoot.find_all('tr'):
                cells = []
                for td in tr.find_all('td'):
                    text = td.get_text(strip=True)
                    cells.append(TableCell(text=text))
                footers.append(TableRow(cells))
        self.headers = headers
        self.rows = rows
        self.footers = footers

    @staticmethod
    def load_from_file(file_path: str) -> 'HtmlTable':
        table = HtmlTable([], [], [])
        with open(file_path, 'r') as file:
            html_content = file.read()
        table.parse_from_html(html_content)
        return table