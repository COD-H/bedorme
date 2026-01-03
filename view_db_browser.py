import sqlite3
import webbrowser
import os

# Path to the database
DB_PATH = 'bedorme.db'
HTML_FILE = 'bedorme_view.html'


def generate_html(db_path):
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all table names
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table';").fetchall()

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>BeDorme Database View</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f9; }
            h1 { color: #333; }
            h2 { color: #555; border-bottom: 2px solid #ddd; padding-bottom: 10px; margin-top: 30px; }
            table { border-collapse: collapse; width: 100%; margin-bottom: 20px; background-color: white; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
            th, td { text-align: left; padding: 12px; border-bottom: 1px solid #ddd; }
            th { background-color: #4CAF50; color: white; }
            tr:hover { background-color: #f5f5f5; }
            .empty { color: #888; font-style: italic; }
        </style>
    </head>
    <body>
        <h1>BeDorme Database Contents</h1>
    """

    for table_name_tuple in tables:
        table_name = table_name_tuple[0]
        html_content += f"<h2>Table: {table_name}</h2>"

        # Get column names
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [col[1] for col in cursor.fetchall()]

        # Get rows
        rows = cursor.execute(f"SELECT * FROM {table_name}").fetchall()

        if not rows:
            html_content += "<p class='empty'>No data in this table.</p>"
        else:
            html_content += "<table><thead><tr>"
            for col in columns:
                html_content += f"<th>{col}</th>"
            html_content += "</tr></thead><tbody>"

            for row in rows:
                html_content += "<tr>"
                for cell in row:
                    html_content += f"<td>{cell}</td>"
                html_content += "</tr>"

            html_content += "</tbody></table>"

    html_content += """
    </body>
    </html>
    """

    conn.close()

    # Write HTML to file
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"HTML view generated: {os.path.abspath(HTML_FILE)}")
    return os.path.abspath(HTML_FILE)


if __name__ == '__main__':
    # Ensure we are looking for the DB in the same directory as the script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    file_path = generate_html(DB_PATH)
    if file_path:
        webbrowser.open('file://' + file_path)
