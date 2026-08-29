# 1.创建在线开发环境

![image-20260827200826164](hidevlabb部署MiniCPM-o 4.5推理2.assets/image-20260827200826164.png)

 使用 自定义镜像

```
  quay.io/ascend/vllm-omni:v0.26.0 
```

# 2.依赖包安装

```
cd /workspace/vllm-omni
VLLM_OMNI_TARGET_DEVICE=npu pip install -v -e . --no-build-isolation \ -i https://mirrors.aliyun.com/pypi/simple/

pip install librosa==0.11.0 s3tokenizer==0.3.0 HyperPyYAML==1.2.3 \
    -i https://mirrors.aliyun.com/pypi/simple/
pip install numpy==1.26.4 -i https://mirrors.aliyun.com/pypi/simple/

python -c "import onnxruntime; print(onnxruntime.__version__)"
```

# 3 启动 

```
vllm serve /workspace/shared_assets/models/OpenBMB/MiniCPM-o-4_5 --omni \
    --trust-remote-code --host 0.0.0.0 --port 8099 --enforce-eager
```

![image-20260827140146095](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260827140146095.png)

以上显示启动完成。

# 4.下载代码

```
git clone https://github.com/hailaobao2026/ai-teaching-miniCPM
```

![image-20260827140931747](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260827140931747.png)

修改配置文件`config/minicpm.json

```json 
{
  "base_url": "https://minicpm45.duckcloud.fun/v1",
  "model": "/tmp/pretrainmodel/MiniCPM-o-4_5",
  "api_key": "",
  "api_key_env": "MINICPM_API_KEY"
}
```

更换本地MiniCPM-o-4_5

```
{
  "base_url": "http://127.0.0.1:8099/v1",
  "model": "/workspace/shared_assets/models/OpenBMB/MiniCPM-o-4_5",
  "api_key": "111111",
  "api_key_env": ""
}
```

后端程序启动运行 

```
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt  -i https://mirrors.aliyun.com/pypi/simple/
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8091
```

前端启动 

 先安装node.js

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
```

![image-20260828103833542](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260828103833542.png)

```
cd /workspace/ai-teaching-miniCPM-main/frontend
npm install
npm run build
npm run dev
```

![image-20260827145427020](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260827145427020.png)

# 5.连接到Trae

![image-20260827162049912](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260827162049912.png)

![image-20260827180159645](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260827180159645.png)

# 6 应用介绍

 我们启动好vllm MiniCPM-o-4_5  接口服务后 以及应用程序的前端和后端程序后 接下来就可以验证一下 应用系统了。

 浏览器输入 http://localhost:3001/  输入账号和密码登录

用户名 admin@example.com 

密码：Admin@Math2026

![image-20260829135748347](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260829135748347.png)

支持文本输入、图片pdf文件上传获取题目信息，

![image-20260829135919087](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260829135919087.png)

 支持摄像头拍题

![image-20260829140111330](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260829140111330.png)

  支持语音输出、语音输入。

![image-20260829140246809](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20260829140246809.png)

  支持课堂总结

