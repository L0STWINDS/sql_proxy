from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import mysql.connector
import os
import re
from dotenv import load_dotenv
import logging
from datetime import timedelta, datetime, date
import json

# 加载环境变量
load_dotenv()

# 创建一个自定义的JSON编码器来处理datetime和timedelta
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(obj, timedelta):
            total_seconds = int(obj.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return super().default(obj)

app = Flask(__name__)
CORS(app)  # 启用CORS

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 从环境变量获取API密钥
READ_ONLY_API_KEY = os.getenv("READ_ONLY_API_KEY")
READ_WRITE_API_KEY = os.getenv("READ_WRITE_API_KEY")

# 检查SQL是否为只读查询
def is_read_only_query(sql):
    # 转换为小写以进行不区分大小写的检查
    sql_lower = sql.lower().strip()
    
    # 检查是否以SELECT开头
    if sql_lower.startswith('select'):
        return True
    
    # 检查是否包含写操作关键字
    write_operations = ['insert', 'update', 'delete', 'drop', 'create', 'alter', 'truncate']
    for op in write_operations:
        if re.search(r'\b' + op + r'\b', sql_lower):
            return False
    
    return True

@app.route('/query', methods=['POST'])
def execute_query():
    # 验证API密钥 - 改为Bearer认证方式
    auth_header = request.headers.get('Authorization')
    api_key = None
    
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            api_key = parts[1]
    
    if not api_key:
        return Response(
            json.dumps({"error": "API密钥缺失，请使用Bearer认证"}, ensure_ascii=False),
            status=401,
            mimetype='application/json'
        )
    
    # 检查API密钥权限
    has_write_permission = api_key == READ_WRITE_API_KEY
    has_read_permission = api_key == READ_ONLY_API_KEY or has_write_permission
    
    if not has_read_permission:
        return Response(
            json.dumps({"error": "无效的API密钥"}, ensure_ascii=False),
            status=401,
            mimetype='application/json'
        )
    
    # 获取请求数据
    data = request.json
    if not data:
        return jsonify({"error": "请求体为空"}), 400
    
    # 验证必要参数
    required_fields = ['sql', 'host', 'database', 'user', 'password']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"缺少必要参数: {field}"}), 400
    
    sql = data['sql']
    
    # 检查SQL是否为只读查询
    if not is_read_only_query(sql) and not has_write_permission:
        return jsonify({"error": "只读API密钥不允许执行写操作"}), 403
    
    # 数据库连接参数
    db_config = {
        'host': data['host'],
        'database': data['database'],
        'user': data['user'],
        'password': data['password'],
        'port': data.get('port', 3306),  # 默认端口为3306
    }
    
    try:
        # 连接到MySQL数据库
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 执行SQL查询
        cursor.execute(sql)
        
        # 如果是SELECT查询，获取结果
        if sql.strip().lower().startswith('select'):
            result = cursor.fetchall()
            response = result  # 直接返回结果数据，不包含rowCount
        else:
            # 对于非SELECT查询，提交更改并返回影响的行数
            conn.commit()
            response = {"rowsAffected": cursor.rowcount}
        
        # 关闭连接
        cursor.close()
        conn.close()
        
        # 使用自定义编码器处理datetime和timedelta
        return Response(
            json.dumps(response, ensure_ascii=False, cls=CustomJSONEncoder),
            mimetype='application/json'
        )
    
    except mysql.connector.Error as err:
        logger.error(f"数据库错误: {err}")
        return Response(
            json.dumps({"error": f"数据库错误: {str(err)}"}, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )
    except Exception as e:
        logger.error(f"执行查询时出错: {e}")
        return Response(
            json.dumps({"error": f"执行查询时出错: {str(e)}"}, ensure_ascii=False),
            status=500,
            mimetype='application/json'
        )

# 同样修改健康检查接口
@app.route('/health', methods=['GET'])
def health_check():
    return Response(
        json.dumps({"status": "healthy"}, ensure_ascii=False),
        mimetype='application/json'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)