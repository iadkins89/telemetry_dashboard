import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import plotly.graph_objs as go
from datetime import datetime
import pandas as pd
import os

# Flask server
server = Flask(__name__)
app = dash.Dash(__name__, server=server, external_stylesheets=[dbc.themes.MINTY])

# DB Config
server.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
server.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(server)

class SensorData(db.Model):
    __tablename__ = 'sensor_data'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(db.DateTime, index=True, nullable=False)
    rssi = db.Column(db.Float, nullable=False)
    snr = db.Column(db.Float, nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f"<SensorData {self.timestamp} {self.temperature} {self.humidity}>"


with server.app_context():
    db.create_all()

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.Img(src='/assets/usa_blue.png', style={'height': '100px'}), width='auto'),
        dbc.Col(html.H1("South Alabama Sonde Telemetry", className="text-left", style={'color': '#154360'}), width=12)
    ], align='center'),
    dbc.Row([
        dbc.Col(dbc.Form([
            dbc.Input(id="csv-filename", placeholder="Enter CSV filename"),
            dbc.Button("Download CSV", id="set-filename-btn", color="primary", className="mt-2"),
            dcc.DatePickerRange(
                id='date-picker-range',
                start_date=datetime.today(),
                end_date=datetime.today(),
                stay_open_on_select =True,
                style={"margin-left": "15px",
                       'padding': '10px'}
            ),
            dcc.ConfirmDialog(
                id='confirm-dialog',
                message=''
            ),
            dcc.Download(id="download-dataframe-csv")
        ]), width=5),
        dbc.Col(html.Div(id='data-container', style={
            'backgroundColor': 'rgba(130,224,170,0.6)',
            'color': '#34495E',
            'height': '200px',
            'overflowY': 'scroll',
            'padding': '10px',
            'border': '2px solid #2ECC71',  # Add border here
            'borderRadius': '10px'}),
                width=7)
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='temperature-graph'), width=6),
        dbc.Col(dcc.Graph(id='humidity-graph'), width=6)
    ]),
    dcc.Interval(id='interval-component', interval=1* 1000, n_intervals=0)  # Update every second
])

data_store = {
    'timestamps': [],
    'rssi': [],
    'snr': [],
    'temperature': [],
    'humidity': []
}

@server.route('/receive_data', methods=['POST'])
def receive_data():
    global csv_filename

    #Parse incoming JSON
    sensor_data = request.json
    rssi_data = sensor_data['hotspots'][0]['rssi']
    snr_data = sensor_data['hotspots'][0]['snr']
    temp_data = sensor_data['decoded']['payload']['temperature']
    hum_data = sensor_data['decoded']['payload']['humidity']
    unix_time_data = sensor_data['decoded']['payload']['timestamp']
    timestamp = datetime.utcfromtimestamp(unix_time_data).strftime('%Y-%m-%dT%H:%M:%S')

    #Add to database
    new_data = SensorData(
        timestamp=timestamp,
        rssi=rssi_data,
        snr=snr_data,
        temperature=temp_data,
        humidity=hum_data
    )
    db.session.add(new_data)
    db.session.commit()

    # Append to data store
    data_store['timestamps'].append(timestamp)
    data_store['rssi'].append(rssi_data)
    data_store['snr'].append(snr_data)
    data_store['temperature'].append(temp_data)
    data_store['humidity'].append(hum_data)

    if len(data_store['timestamps']) > 10:
        data_store['timestamps'].pop(0)
        data_store['rssi'].pop(0)
        data_store['snr'].pop(0)
        data_store['temperature'].pop(0)
        data_store['humidity'].pop(0)

    # Emit the data to all connected clients
    return jsonify({'message': 'Data received and broadcasted.'}), 200

@app.callback(
    Output('data-container', 'children'),
    [Input('interval-component', 'n_intervals')]
)
def update_data_container(n):
    data_elements = [
        html.P(
            f"Time: {ts}, RSSI: {data_store['rssi'][i]}, SNR: {data_store['snr'][i]}, Temperature: {data_store['temperature'][i]}, Humidity: {data_store['humidity'][i]}",
            className='data-item')
        for i, ts in enumerate(data_store['timestamps'])
    ]
    return data_elements

@app.callback(
    Output('temperature-graph', 'figure'),
    [Input('interval-component', 'n_intervals')]
)
def update_temperature_graph(n):
    return {
        'data': [go.Scatter(x=data_store['timestamps'], y=data_store['temperature'], mode='lines+markers',
                            name='Temperature', marker={'color': 'red'})],
        'layout': go.Layout(title='Temperature', xaxis={'title': 'Time'}, yaxis={'title': 'Temperature (°C)'})
    }

@app.callback(
    Output('humidity-graph', 'figure'),
    [Input('interval-component', 'n_intervals')]
)
def update_humidity_graph(n):
    return {
        'data': [go.Scatter(x=data_store['timestamps'], y=data_store['humidity'], mode='lines+markers', name='Humidity',
                            marker={'color': 'blue'})],
        'layout': go.Layout(title='Humidity', xaxis={'title': 'Time'}, yaxis={'title': 'Humidity (%)'})
    }


@app.callback(
    Output('confirm-dialog', 'displayed'),
    Output('confirm-dialog', 'message'),
    Output('download-dataframe-csv', 'data'),
    [Input('set-filename-btn', 'n_clicks')],
    [State('date-picker-range', 'start_date'),
     State('date-picker-range', 'end_date'),
     State('csv-filename', 'value')]
)
def update_output(n_clicks, start_date, end_date, filename):
    if n_clicks > 0:
        if not start_date or not end_date or not filename:
            return True, 'Please provide a valid date range and filename.', None

        data = query_data(start_date, end_date)
        if not data:
            return True, 'No data found for the given date range.', None

        saved_csv_file = save_data_to_csv(data, f"{filename}.csv")
        return False, '', dict(content=saved_csv_file, filename=f"{filename}.csv")
    return False, '', None

def query_data(start_date, end_date):
    start_date = start_date.split('T')[0]  # Get only the date part
    end_date = end_date.split('T')[0]  # Get only the date part

    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()

    result = db.session.query(SensorData).filter(SensorData.timestamp >= start_dt, SensorData.timestamp <= end_dt).all()
    return result


def save_data_to_csv(data, filename='output.csv'):
    data_dict = {
        'id': [d.id for d in data],
        'timestamp': [d.timestamp for d in data],
        'rssi': [d.rssi for d in data],
        'snr': [d.snr for d in data],
        'temperature': [d.temperature for d in data],
        'humidity': [d.humidity for d in data]
    }
    df = pd.DataFrame(data_dict)
    saved_csv_file = df.to_csv(index=False)
    return saved_csv_file

