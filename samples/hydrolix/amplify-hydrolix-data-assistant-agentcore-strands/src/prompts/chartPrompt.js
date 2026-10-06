// The chart-model prompt. It lives in code, not in the copied env.js, so a fix to it
// reaches every installation (RB11: it asks for formatter names, never JavaScript).
// The names are the ones utils/chartFormatters.js implements.

export const CHART_PROMPT = `
Create detailed ApexCharts.js configurations based on the information provided to support the answer. Focus on meaningful data analysis and visually appealing charts.

Input Data:

<information>
    <summary>
        <<answer>>
    </summary>
    <data_sources>
        <<data_sources>>
    </data_sources>
</information>

The following is the only required output format for a Chart:

<has_chart>1</has_chart>
<chart_type>[bar/line/pie/etc]</chart_type>
<chart_configuration>[JSON validate format with series and options]</chart_configuration>
<caption>[Insightful analysis about the data chart in 20-40 words]</caption>

If you do not have a chart configuration, use only the following output format:

<has_chart>0</has_chart>
<rationale>[The reason to do not generate a chart configuration, max 12 words]</rationale>

- Provide the caption and chart information in the same language as the summary information.

Chart Requirements:

   - Provide only 1 chart configuration
   - Use the appropriate chart type based on the data
   - Each chart must include:
      - Complete series and options configuration

ApexChartsx Technical Specifications:

    - Never write JavaScript. To format values, set "formatter" to one of these names only: fixed2, integer, percent, currency, label_and_value, label_and_percent
    - Use standard ApexCharts.js for React.js syntax
    - Format all property names and string values with double quotes
    - Include appropriate titles, subtitles and axis labels
    - Configure for light mode viewing
    - Use default text format styles
    - Format decimal values to two places with the fixed2 (or percent, currency) formatter name
    - Use plain values only: no JavaScript, no functions, no moment.js

ApexChartsx Rules to Avoid Known Erros:

   - Do not use Multiple Y Axis for bars, those are not supported.
   - In JSON format, avoid the error: raise JSONDecodeError("Expecting value", s, err.value) from None
   - Do not use 'udenfined' values

Example Chart Configurations:

<ChartExamples>
  <Chart description="Line Basic">
    <type>line</type>
    <configuartion>
{
   "series":[
      {
         "name":"Desktops",
         "data":[
            10,
            41,
            35,
            51,
            49,
            62,
            69,
            91,
            148
         ]
      }
   ],
   "options":{
      "chart":{
         "height":420,
         "type":"line",
         "zoom":{
            "enabled":false
         }
      },
      "dataLabels":{
         "enabled":false
      },
      "stroke":{
         "curve":"straight"
      },
      "title":{
         "text":"Product Trends by Month",
         "align":"left"
      },
      "grid":{
         "row":{
            "colors":[
               "#f3f3f3",
               "transparent"
            ],
            :0.5
         }
      },
      "xaxis":{
         "categories":[
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep"
         ]
      }
   }
}
    </configuartion>
  </Chart>

  <Chart description="Bar Funnel">
    <type>bar</type>
    <configuartion>
{
   "series":[
      {
         "name":"Funnel Series",
         "data":[
            1380,
            1100,
            990,
            880,
            740,
            548,
            330,
            200
         ]
      }
   ],
   "options":{
      "chart":{
         "type":"bar",
         "height":420,
         "dropShadow":{
            "enabled":true
         }
      },
      "plotOptions":{
         "bar":{
            "borderRadius":0,
            "horizontal":true,
            "barHeight":"80%",
            "isFunnel":true
         }
      },
      "dataLabels":{
         "enabled":true,
         "formatter":"label_and_value",
         "dropShadow":{
            "enabled":true
         }
      },
      "title":{
         "text":"Recruitment Funnel",
         "align":"middle"
      },
      "xaxis":{
         "categories":[
            "Sourced",
            "Screened",
            "Assessed",
            "HR Interview",
            "Technical",
            "Verify",
            "Offered",
            "Hired"
         ]
      },
      "legend":{
         "show":false
      }
   }
}
    <configuartion>
  </Chart>

  <Chart description="Bar Basic">
    <type>bar</type>
    <configuartion>
{
   "series":[
      {
         "data":[
            400,
            430,
            448,
            470,
            540,
            580,
            690,
            1100,
            1200,
            1380
         ]
      }
   ],
   "options":{
      "chart":{
         "type":"bar",
         "height":420
      },
      "plotOptions":{
         "bar":{
            "borderRadius":4,
            "borderRadiusApplication":"end",
            "horizontal":true
         }
      },
      "dataLabels":{
         "enabled":false
      },
      "xaxis":{
         "categories":[
            "South Korea",
            "Canada",
            "United Kingdom",
            "Netherlands",
            "Italy",
            "France",
            "Japan",
            "United States",
            "China",
            "Germany"
         ]
      }
   }
}
    <configuartion>
  </Chart>

  <Chart description="Simple Pie">
    <type>pie</type>
    <configuartion>
{
  "series": [2077, 1036.75, 384.99, 277.49],
  "options": {
    "chart": {
      "type": "pie",
      "height": 420
    },
    "labels": ["North America", "Europe", "Other Regions", "Japan"],
    "title": {
      "text": "Video Game Sales Distribution by Region (2000-2010)",
      "align": "center"
    },
    "subtitle": {
      "text": "Total Global Sales: 3,779.72 million units",
      "align": "center"
    },
    "dataLabels": {
      "enabled": true,
      "formatter": "label_and_percent"
    },
    "legend": {
      "position": "bottom"
    },
    "colors": ["#008FFB", "#00E396", "#FEB019", "#FF4560"]
  }
}
    <configuartion>
  </Chart>

</ChartExamples>`;
