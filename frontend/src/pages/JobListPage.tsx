import {
  CheckCircleOutlined,
  EditOutlined,
  FileSearchOutlined,
  InboxOutlined,
  MoreOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Dropdown,
  Empty,
  Modal,
  Skeleton,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

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
  const { jobId: currentJobId } = useParams()
  const queryClient = useQueryClient()
  const [modal, modalContextHolder] = Modal.useModal()
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
    const current = job.id === currentJobId

    function confirmArchive() {
      modal.confirm({
        title: '确认归档该职位？',
        content: '归档后职位与历史标准仍可查看，但不能继续修改。',
        okText: '确认归档',
        cancelText: '取消',
        okButtonProps: { danger: true },
        onOk: () => archiveMutation.mutateAsync(job.id),
      })
    }

    return (
      <Card key={job.id} className={`job-card${current ? ' job-card--current' : ''}`}>
        <div className="job-card-heading">
          <div>
            <Space size="small" wrap>
              <Title level={4}>{job.title}</Title>
              <Tag color={archived ? 'default' : 'blue'}>{archived ? '已归档' : '进行中'}</Tag>
              {current && (
                <Tag color="processing" icon={<CheckCircleOutlined />}>
                  当前岗位
                </Tag>
              )}
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

        <div className="job-card-footer">
          <Text type="secondary" className="job-card-context-hint">
            {current ? '已选为当前岗位，可从左侧进入各业务模块' : '选择后可从左侧进入各业务模块'}
          </Text>
          <div className="job-card-actions">
            {!current && (
              <Button type="primary" onClick={() => navigate(`/jobs/${job.id}`)}>
                设为当前岗位
              </Button>
            )}
            <Button
              icon={<EditOutlined />}
              onClick={() => navigate(`/jobs/${job.id}/edit`)}
            >
              {archived ? '查看职位' : '编辑职位'}
            </Button>
            {!archived && (
              <Dropdown
                trigger={['click']}
                menu={{
                  items: [
                    {
                      key: 'archive',
                      danger: true,
                      icon: <InboxOutlined />,
                      label: '归档职位',
                    },
                  ],
                  onClick: ({ key }) => {
                    if (key === 'archive') confirmArchive()
                  },
                }}
              >
                <Button
                  icon={<MoreOutlined />}
                  aria-label={`更多操作 ${job.title}`}
                  loading={archiveMutation.isPending}
                />
              </Dropdown>
            )}
          </div>
        </div>
      </Card>
    )
  }

  return (
    <>
      {modalContextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>岗位管理</Title>
          <Text type="secondary">维护岗位信息并选择当前岗位工作区</Text>
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
