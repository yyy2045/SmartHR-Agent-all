import { EyeOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Pagination,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'

import {
  fetchCommunicationRecord,
  fetchCommunicationRecords,
  type CommunicationChannel,
  type CommunicationContextType,
  type CommunicationRecordSummaryRecord,
} from '../api/client'

const { Text, Title, Paragraph } = Typography
const PAGE_SIZE = 20

const contextOptions: { label: string; value: CommunicationContextType }[] = [
  { value: 'interview_round', label: '面试沟通' },
  { value: 'offer', label: 'Offer 沟通' },
  { value: 'onboarding', label: '入职沟通' },
]

const contextLabels: Record<CommunicationContextType, string> = {
  interview_round: '面试沟通',
  offer: 'Offer 沟通',
  onboarding: '入职沟通',
}

const channelLabels: Record<CommunicationChannel, string> = {
  wechat: '微信',
  phone: '电话',
  sms: '短信',
  email: '邮件',
  other: '其他',
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function channelTag(channel: CommunicationChannel, channelDetail?: string | null) {
  const label = channel === 'other' && channelDetail ? channelDetail : channelLabels[channel]
  const color = channel === 'email' ? 'blue' : channel === 'phone' ? 'green' : 'default'
  return <Tag color={color}>{label}</Tag>
}

export function CommunicationRecordsPage() {
  const [page, setPage] = useState(1)
  const [contextType, setContextType] = useState<CommunicationContextType | undefined>()
  const [contextIdDraft, setContextIdDraft] = useState('')
  const [contextId, setContextId] = useState('')
  const [applicationIdDraft, setApplicationIdDraft] = useState('')
  const [applicationId, setApplicationId] = useState('')
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null)
  const offset = (page - 1) * PAGE_SIZE

  const records = useQuery({
    queryKey: ['communications', { contextType, contextId, applicationId, page }],
    queryFn: () =>
      fetchCommunicationRecords({
        contextType,
        contextId: contextId || undefined,
        applicationId: applicationId || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    staleTime: 15_000,
  })

  const selectedRecord = useQuery({
    queryKey: ['communication', selectedRecordId],
    queryFn: () => fetchCommunicationRecord(selectedRecordId!),
    enabled: Boolean(selectedRecordId),
  })

  function applyFilters() {
    setContextId(contextIdDraft.trim())
    setApplicationId(applicationIdDraft.trim())
    setPage(1)
  }

  function clearFilters() {
    setContextType(undefined)
    setContextIdDraft('')
    setContextId('')
    setApplicationIdDraft('')
    setApplicationId('')
    setPage(1)
  }

  return (
    <div className="communication-records-page">
      <div className="page-heading">
        <div>
          <Title level={2}>沟通留痕</Title>
          <Text type="secondary">
            查询候选人沟通发送记录、收件人脱敏快照、正文快照和后续更正历史。
          </Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void records.refetch()}
          loading={records.isFetching}
        >
          刷新
        </Button>
      </div>

      {records.isError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取沟通留痕"
          description={records.error.message}
          action={<Button onClick={() => void records.refetch()}>重试</Button>}
        />
      )}

      <section className="panel-card communication-records-toolbar">
        <Select
          aria-label="筛选沟通场景"
          allowClear
          placeholder="全部场景"
          value={contextType}
          options={contextOptions}
          onChange={(value) => {
            setContextType(value)
            setPage(1)
          }}
        />
        <Input
          aria-label="按业务对象 ID 筛选"
          allowClear
          value={contextIdDraft}
          placeholder="业务对象 ID"
          onChange={(event) => setContextIdDraft(event.target.value)}
          onPressEnter={applyFilters}
        />
        <Input
          aria-label="按应聘记录 ID 筛选"
          allowClear
          value={applicationIdDraft}
          placeholder="应聘记录 ID"
          onChange={(event) => setApplicationIdDraft(event.target.value)}
          onPressEnter={applyFilters}
        />
        <Space wrap>
          <Button type="primary" onClick={applyFilters}>
            查询
          </Button>
          <Button onClick={clearFilters}>清空</Button>
        </Space>
      </section>

      <section className="panel-card communication-records-table-panel">
        <Table<CommunicationRecordSummaryRecord>
          rowKey="id"
          loading={records.isPending}
          dataSource={records.data?.items ?? []}
          pagination={false}
          locale={{ emptyText: <Empty description="暂无沟通留痕" /> }}
          scroll={{ x: 980 }}
          columns={[
            {
              title: '候选人与主题',
              key: 'subject',
              render: (_, record) => (
                <Space direction="vertical" size={2}>
                  <Space size="small" wrap>
                    <Text strong>{record.candidate_name_snapshot}</Text>
                    <Tag>{contextLabels[record.context_type]}</Tag>
                    {record.correction_count > 0 && (
                      <Tag color="orange">已更正 {record.correction_count}</Tag>
                    )}
                  </Space>
                  <Text type="secondary">{record.subject_snapshot}</Text>
                </Space>
              ),
            },
            {
              title: '渠道',
              key: 'channel',
              width: 150,
              render: (_, record) => channelTag(record.channel, record.channel_detail),
            },
            {
              title: '收件人',
              dataIndex: 'recipient_masked',
              width: 150,
            },
            {
              title: '发送时间',
              dataIndex: 'sent_at',
              width: 180,
              render: formatDateTime,
            },
            {
              title: '操作',
              key: 'actions',
              fixed: 'right',
              width: 120,
              render: (_, record) => (
                <Button icon={<EyeOutlined />} onClick={() => setSelectedRecordId(record.id)}>
                  详情
                </Button>
              ),
            },
          ]}
        />
      </section>

      {Boolean(records.data?.total) && (
        <Pagination
          className="communication-records-pagination"
          current={page}
          pageSize={PAGE_SIZE}
          total={records.data?.total ?? 0}
          showSizeChanger={false}
          onChange={setPage}
        />
      )}

      <Drawer
        title="沟通留痕详情"
        width={760}
        open={Boolean(selectedRecordId)}
        onClose={() => setSelectedRecordId(null)}
      >
        {selectedRecord.isError && (
          <Alert
            type="error"
            showIcon
            message="无法读取沟通详情"
            description={selectedRecord.error.message}
          />
        )}
        {selectedRecord.data && (
          <Space direction="vertical" size="large" className="communication-record-detail">
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="候选人">
                {selectedRecord.data.candidate_name_snapshot}
              </Descriptions.Item>
              <Descriptions.Item label="沟通场景">
                {contextLabels[selectedRecord.data.context_type]}
              </Descriptions.Item>
              <Descriptions.Item label="渠道">
                {channelTag(selectedRecord.data.channel, selectedRecord.data.channel_detail)}
              </Descriptions.Item>
              <Descriptions.Item label="收件人">
                {selectedRecord.data.recipient_masked}
              </Descriptions.Item>
              <Descriptions.Item label="发送时间">
                {formatDateTime(selectedRecord.data.sent_at)}
              </Descriptions.Item>
              <Descriptions.Item label="登记人">
                {selectedRecord.data.created_by_display_name}
              </Descriptions.Item>
              <Descriptions.Item label="历史补录">
                {selectedRecord.data.is_historical ? selectedRecord.data.historical_note : '否'}
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Title level={4}>沟通快照</Title>
              <Paragraph strong>{selectedRecord.data.subject_snapshot}</Paragraph>
              <pre className="communication-record-body-preview">
                {selectedRecord.data.body_snapshot}
              </pre>
              <Text type="secondary">
                系统仅保存脱敏后的收件人和安全正文快照，不展示完整手机号、邮箱、薪酬明细或 Offer 原始链接。
              </Text>
            </div>

            <div>
              <Title level={4}>更正历史</Title>
              {selectedRecord.data.corrections.length ? (
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={selectedRecord.data.corrections}
                  columns={[
                    {
                      title: '序号',
                      dataIndex: 'correction_sequence',
                      width: 80,
                      render: (value: number) => <Tag color="orange">#{value}</Tag>,
                    },
                    { title: '主题', dataIndex: 'subject_snapshot' },
                    {
                      title: '原因',
                      dataIndex: 'correction_reason',
                      ellipsis: true,
                    },
                    {
                      title: '时间',
                      dataIndex: 'sent_at',
                      width: 180,
                      render: formatDateTime,
                    },
                  ]}
                />
              ) : (
                <Empty description="暂无更正记录" />
              )}
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}
