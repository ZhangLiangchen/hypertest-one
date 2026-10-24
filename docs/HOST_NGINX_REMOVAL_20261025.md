# 宿主 nginx 移除

日期：2026-10-25（Asia/Singapore；操作窗口 UTC 2026-10-24 17:31 起）。

按用户指令停止并卸载宿主 nginx，后续应用服务部署统一采用 Docker。
本次只处理宿主 nginx，不迁移既有独立 Cloud Worker / Bridge，不更换应用镜像或 schema。

## 操作与保留

- 执行 `systemctl disable --now nginx.service`、`systemctl mask nginx.service`。
- 执行 `apt-get -y --no-auto-remove remove nginx nginx-common`，只移除这两个包；
  未 purge、autoremove 或删除缓存。两包原版本均为 `1.26.3-3+deb13u10`。
- 清除原服务 failed 记账，最终为 `masked / inactive / dead`、MainPID 0。
- `/usr/sbin/nginx` 已移除；`nginx-common` 的 rc 状态表示只保留配置。
  `/etc/nginx`、`/var/log/nginx`、`/var/lib/nginx` 保留，Docker 挂载配置与 TLS 文件保留。
- 卸载前 nginx 包为半配置状态；卸载后 `dpkg --audit` 无输出。

## 资源收益与验证

APT 报告包文件释放 **1,905,664 字节（约 1.82 MiB）**。操作前后根盘可用量净增
1,785,856 字节（约 1.70 MiB），该文件系统差值包含同时发生的日志等写入，不等于包大小。
宿主 nginx 操作前已启动失败、MainPID 0；原两个 nginx 进程均属于 Docker，
因此本次没有释放运行中宿主 nginx 的内存，也没有停止容器进程。

五容器全部 running / healthy，容器 ID、image、StartedAt 与重启次数均保持；
API health、Web 根页及 nginx health 均 HTTP 200。独立 Cloud Worker / Bridge 均
active / running。未重启应用或数据库，未触发模型 / SUT 或用户业务验收。

私有操作回执：`/var/lib/hypertest-cloud/delivery/20261025-host-nginx-removal/`，
含前后服务、包状态、容器身份与健康检查。服务停止、卸载后的旧 failed 状态及
reset-failed 后状态分别保留在回执字段中。
