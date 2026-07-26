import {
  EditOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  ProjectOutlined,
  PlusOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Popconfirm, Skeleton, Space, Switch, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, archiveJob, fetchJobs, type JobRecord } from '../api/client'

const { Title, Text, Paragraph } = Typography

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function JobListPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [includeArchived, setIncludeArchived] = useState(false)
  const jobs = useQuery({
    queryKey: ['jobs', { includeArchived }],
    queryFn: () => fetchJobs(includeArchived),
  })
  const archiveMutation = useMutation({
    mutationFn: archiveJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  function renderJob(job: JobRecord) {
    const archived = job.status === 'archived'
    return (
      <Card key={job.id} className="job-card">
        <div className="job-card-heading">
          <div>
            <Space size="small" wrap>
              <Title level={4}>{job.title}</Title>
              <Tag color={archived ? 'default' : 'blue'}>{archived ? '已归档' : '进行中'}</Tag>
            </Space>
            <Text type="secondary">{job.department || '未填写部门'}</Text>
          </div>
          <Text type="secondary" className="job-updated-at">
            更新于 {formatDate(job.updated_at)}
          </Text>
        </div>

        <Paragraph ellipsis={{ rows: 2 }} className="job-jd-preview">
          {job.original_jd}
        </Paragraph>

        <Space wrap>
          <Button
            icon={<ProjectOutlined />}
            onClick={() => navigate(`/jobs/${job.id}/pipeline`)}
          >
            流程看板
          </Button>
          <Button
            icon={<FileSearchOutlined />}
            onClick={() => navigate(`/jobs/${job.id}/results`)}
          >
            筛选结果
          </Button>
          <Button
            icon={<FolderOpenOutlined />}
            onClick={() => navigate(`/jobs/${job.id}/batches`)}
          >
            简历批次
          </Button>
          <Button
            type="primary"
            icon={<SettingOutlined />}
            onClick={() => navigate(`/jobs/${job.id}/criteria`)}
          >
            {archived ? '查看标准' : '配置筛选标准'}
          </Button>
          <Button
            icon={<EditOutlined />}
            disabled={archived}
            onClick={() => navigate(`/jobs/${job.id}/edit`)}
          >
            编辑职位
          </Button>
          {!archived && (
            <Popconfirm
              title="确认归档该职位？"
              description="归档后职位与历史标准仍可查看，但不能继续修改。"
              okText="确认归档"
              cancelText="取消"
              onConfirm={() => archiveMutation.mutate(job.id)}
            >
              <Button danger icon={<InboxOutlined />} loading={archiveMutation.isPending}>
                归档
              </Button>
            </Popconfirm>
          )}
        </Space>
      </Card>
    )
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <Title level={2}>职位筛选</Title>
          <Text type="secondary">创建职位并维护可版本化的筛选标准</Text>
        </div>
        <Space wrap>
          <Space size="small">
            <Switch checked={includeArchived} onChange={setIncludeArchived} />
            <Text>显示已归档</Text>
          </Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/jobs/new')}>
            新建职位
          </Button>
        </Space>
      </div>

      {archiveMutation.isError && (
        <Alert
          type="error"
          showIcon
          closable
          className="page-alert"
          message={
            archiveMutation.error instanceof ApiError
              ? archiveMutation.error.message
              : '归档职位失败'
          }
        />
      )}

      {jobs.isPending && (
        <div className="panel-card">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      )}
      {jobs.isError && (
        <Alert
          type="error"
          showIcon
          message="无法读取职位列表"
          description={jobs.error.message}
          action={<Button onClick={() => void jobs.refetch()}>重试</Button>}
        />
      )}
      {jobs.isSuccess && jobs.data.length === 0 && (
        <section className="empty-workspace" aria-label="职位列表">
          <Empty
            image={<FileSearchOutlined className="empty-icon" />}
            description={includeArchived ? '没有职位记录' : '暂无进行中的职位'}
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/jobs/new')}>
              创建第一个职位
            </Button>
          </Empty>
        </section>
      )}
      {jobs.isSuccess && jobs.data.length > 0 && (
        <section className="job-grid" aria-label="职位列表">
          {jobs.data.map(renderJob)}
        </section>
      )}
    </>
  )
}
