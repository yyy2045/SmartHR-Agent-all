import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Form, Input, Skeleton, Space, Typography, message } from 'antd'
import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, createJob, fetchJob, updateJob, type JobInput } from '../api/client'

const { Title, Text } = Typography

export function JobFormPage() {
  const { jobId } = useParams()
  const editing = Boolean(jobId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm<JobInput>()
  const [messageApi, contextHolder] = message.useMessage()
  const job = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: editing,
  })
  const saveMutation = useMutation({
    mutationFn: (values: JobInput) =>
      editing ? updateJob(jobId!, values) : createJob(values),
    onSuccess: async (savedJob) => {
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      messageApi.success(editing ? '职位已保存' : '职位已创建')
      navigate(editing ? '/' : `/jobs/${savedJob.id}/criteria`, { replace: true })
    },
  })

  useEffect(() => {
    if (job.data) {
      form.setFieldsValue({
        title: job.data.title,
        department: job.data.department,
        original_jd: job.data.original_jd,
      })
    }
  }, [form, job.data])

  if (editing && job.isPending) {
    return <Skeleton active paragraph={{ rows: 8 }} />
  }

  if (editing && job.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message="无法读取职位"
        description={job.error.message}
        action={<Button onClick={() => void job.refetch()}>重试</Button>}
      />
    )
  }

  const archived = job.data?.status === 'archived'

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>{editing ? '编辑职位' : '新建职位'}</Title>
          <Text type="secondary">职位信息和原始 JD 将作为后续筛选标准与 AI 分析的基础</Text>
        </div>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
          返回
        </Button>
      </div>

      {archived && (
        <Alert type="warning" showIcon message="该职位已归档，不能继续编辑" className="page-alert" />
      )}
      {saveMutation.isError && (
        <Alert
          type="error"
          showIcon
          message={
            saveMutation.error instanceof ApiError ? saveMutation.error.message : '保存职位失败'
          }
          className="page-alert"
        />
      )}

      <section className="panel-card form-panel">
        <Form<JobInput>
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{ department: '' }}
          disabled={archived}
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <Form.Item
            label="职位名称"
            name="title"
            rules={[{ required: true, whitespace: true, message: '请输入职位名称' }]}
          >
            <Input maxLength={200} showCount placeholder="例如：高级后端工程师" size="large" />
          </Form.Item>

          <Form.Item label="所属部门" name="department">
            <Input maxLength={100} showCount placeholder="例如：研发中心" size="large" />
          </Form.Item>

          <Form.Item
            label="原始 JD"
            name="original_jd"
            rules={[{ required: true, whitespace: true, message: '请粘贴职位描述' }]}
            extra="当前阶段先由招聘专员人工配置筛选标准，后续将支持 AI 结构化 JD。"
          >
            <Input.TextArea
              rows={14}
              maxLength={50_000}
              showCount
              placeholder="粘贴岗位职责、任职要求和加分项……"
            />
          </Form.Item>

          <Space>
            <Button onClick={() => navigate(-1)}>取消</Button>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SaveOutlined />}
              loading={saveMutation.isPending}
              disabled={archived}
            >
              {editing ? '保存修改' : '创建并配置标准'}
            </Button>
          </Space>
        </Form>
      </section>
    </>
  )
}
