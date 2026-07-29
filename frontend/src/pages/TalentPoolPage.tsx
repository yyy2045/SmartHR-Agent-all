import {
  DatabaseOutlined,
  EditOutlined,
  InboxOutlined,
  MailOutlined,
  PhoneOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  UserDeleteOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Avatar,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  ApiError,
  archiveTalentPoolGroup,
  createTalentPoolGroup,
  fetchTalentPoolGroups,
  fetchTalentPoolMemberships,
  removeTalentPoolMemberships,
  updateTalentPoolGroup,
  type TalentPoolGroupRecord,
  type TalentPoolGroupStatus,
  type TalentPoolMembershipRecord,
  type TalentPoolMembershipStatus,
} from '../api/client'
import { useAuth } from '../auth/context'

const { Title, Text } = Typography
const PAGE_SIZE = 20

interface GroupFormValues {
  name: string
  description?: string
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
}

export function TalentPoolPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messageApi, messageContext] = message.useMessage()
  const [groupForm] = Form.useForm<GroupFormValues>()
  const [memberSearchDraft, setMemberSearchDraft] = useState('')
  const [memberSearch, setMemberSearch] = useState('')
  const [memberStatus, setMemberStatus] = useState<TalentPoolMembershipStatus>('active')
  const [memberGroupId, setMemberGroupId] = useState<string>()
  const [memberPage, setMemberPage] = useState(1)
  const [groupSearchDraft, setGroupSearchDraft] = useState('')
  const [groupSearch, setGroupSearch] = useState('')
  const [groupStatus, setGroupStatus] = useState<TalentPoolGroupStatus>('active')
  const [groupPage, setGroupPage] = useState(1)
  const [editingGroup, setEditingGroup] = useState<TalentPoolGroupRecord | null>()
  const [groupModalOpen, setGroupModalOpen] = useState(false)
  const [archivingGroup, setArchivingGroup] = useState<TalentPoolGroupRecord>()
  const [archiveReason, setArchiveReason] = useState('')
  const [removingMember, setRemovingMember] = useState<TalentPoolMembershipRecord>()
  const [removeReason, setRemoveReason] = useState('')
  const activeView = searchParams.get('view') === 'groups' ? 'groups' : 'candidates'
  const canWrite = auth.user?.roles.some((role) =>
    ['administrator', 'recruiter'].includes(role),
  )

  const groupOptions = useQuery({
    queryKey: ['talent-pool-groups', { status: 'all', limit: 100 }],
    queryFn: () => fetchTalentPoolGroups({ status: 'all', limit: 100 }),
  })
  const memberFilters = useMemo(
    () => ({
      status: memberStatus,
      groupStatus: 'active' as const,
      groupId: memberGroupId,
      query: memberSearch,
      limit: PAGE_SIZE,
      offset: (memberPage - 1) * PAGE_SIZE,
    }),
    [memberGroupId, memberPage, memberSearch, memberStatus],
  )
  const memberships = useQuery({
    queryKey: ['talent-pool-memberships', memberFilters],
    queryFn: () => fetchTalentPoolMemberships(memberFilters),
    enabled: activeView === 'candidates',
  })
  const groupFilters = useMemo(
    () => ({
      status: groupStatus,
      query: groupSearch,
      limit: PAGE_SIZE,
      offset: (groupPage - 1) * PAGE_SIZE,
    }),
    [groupPage, groupSearch, groupStatus],
  )
  const groups = useQuery({
    queryKey: ['talent-pool-groups', groupFilters],
    queryFn: () => fetchTalentPoolGroups(groupFilters),
    enabled: activeView === 'groups',
  })

  async function refreshTalentPool() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['talent-pool-groups'] }),
      queryClient.invalidateQueries({ queryKey: ['talent-pool-memberships'] }),
    ])
  }

  const saveGroupMutation = useMutation({
    mutationFn: (values: GroupFormValues) =>
      editingGroup
        ? updateTalentPoolGroup(editingGroup.id, editingGroup.version, {
            name: values.name.trim(),
            description: values.description?.trim() || null,
          })
        : createTalentPoolGroup(values.name.trim(), values.description?.trim() || null),
    onSuccess: async () => {
      messageApi.success(editingGroup ? '人才分组已更新' : '人才分组已创建')
      setGroupModalOpen(false)
      setEditingGroup(undefined)
      groupForm.resetFields()
      await refreshTalentPool()
    },
    onError: (error) => messageApi.error(errorMessage(error, '保存人才分组失败')),
  })
  const archiveMutation = useMutation({
    mutationFn: () =>
      archiveTalentPoolGroup(
        archivingGroup!.id,
        archivingGroup!.version,
        archiveReason.trim(),
      ),
    onSuccess: async () => {
      messageApi.success('人才分组已归档')
      setArchivingGroup(undefined)
      setArchiveReason('')
      await refreshTalentPool()
    },
    onError: (error) => messageApi.error(errorMessage(error, '归档人才分组失败')),
  })
  const removeMutation = useMutation({
    mutationFn: () => {
      const group = groupOptions.data?.items.find(
        (item) => item.id === removingMember!.group_id,
      )
      if (!group) throw new Error('人才分组状态已变化')
      return removeTalentPoolMemberships(
        group.id,
        group.version,
        [removingMember!.candidate_id],
        removeReason.trim(),
      )
    },
    onSuccess: async () => {
      messageApi.success('候选人已移出分组')
      setRemovingMember(undefined)
      setRemoveReason('')
      await refreshTalentPool()
    },
    onError: (error) => messageApi.error(errorMessage(error, '移出人才分组失败')),
  })

  function openGroupEditor(group?: TalentPoolGroupRecord) {
    setEditingGroup(group ?? null)
    groupForm.setFieldsValue({
      name: group?.name ?? '',
      description: group?.description ?? '',
    })
    setGroupModalOpen(true)
  }

  const memberColumns: ColumnsType<TalentPoolMembershipRecord> = [
    {
      title: '候选人',
      key: 'candidate',
      width: 260,
      render: (_, item) => (
        <div className="talent-candidate-cell">
          <Avatar icon={<UserOutlined />} />
          <div>
            <Text strong>{item.candidate_name || '姓名待补充'}</Text>
            <Text type="secondary" copyable={{ text: item.candidate_code }}>
              {item.candidate_code}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: '联系方式',
      key: 'contact',
      width: 220,
      responsive: ['md'],
      render: (_, item) => (
        <Space direction="vertical" size={0}>
          <Text type={item.phone ? undefined : 'secondary'}>
            <PhoneOutlined /> {item.phone || '不可见或未识别'}
          </Text>
          <Text type={item.email ? undefined : 'secondary'} ellipsis>
            <MailOutlined /> {item.email || '不可见或未识别'}
          </Text>
        </Space>
      ),
    },
    {
      title: '人才分组',
      dataIndex: 'group_name',
      width: 160,
      render: (value: string) => <Tag color="blue">{value}</Tag>,
    },
    {
      title: '入库原因',
      dataIndex: 'reason',
      ellipsis: true,
    },
    {
      title: '加入日期',
      dataIndex: 'joined_at',
      width: 120,
      responsive: ['lg'],
      render: formatDate,
    },
    ...(canWrite
      ? [
          {
            title: '操作',
            key: 'action',
            width: 80,
            fixed: 'right' as const,
            render: (_: unknown, item: TalentPoolMembershipRecord) => (
              <Button
                type="text"
                danger
                aria-label={`移出 ${item.candidate_name || item.candidate_code}`}
                icon={<UserDeleteOutlined />}
                onClick={() => setRemovingMember(item)}
              />
            ),
          },
        ]
      : []),
  ]

  const groupColumns: ColumnsType<TalentPoolGroupRecord> = [
    {
      title: '分组名称',
      dataIndex: 'name',
      width: 220,
      render: (value: string, group) => (
        <Space wrap>
          <Text strong>{value}</Text>
          {group.is_archived && <Tag>已归档</Tag>}
        </Space>
      ),
    },
    { title: '当前成员', dataIndex: 'member_count', width: 100, align: 'center' },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
      render: (value: string | null) => value || <Text type="secondary">未填写</Text>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 120,
      responsive: ['md'],
      render: formatDate,
    },
    ...(canWrite
      ? [
          {
            title: '操作',
            key: 'action',
            width: 110,
            fixed: 'right' as const,
            render: (_: unknown, group: TalentPoolGroupRecord) => (
              <Space size={2}>
                <Button
                  type="text"
                  aria-label={`编辑 ${group.name}`}
                  disabled={group.is_archived}
                  icon={<EditOutlined />}
                  onClick={() => openGroupEditor(group)}
                />
                <Button
                  type="text"
                  aria-label={`归档 ${group.name}`}
                  disabled={group.is_archived}
                  icon={<InboxOutlined />}
                  onClick={() => setArchivingGroup(group)}
                />
              </Space>
            ),
          },
        ]
      : []),
  ]

  return (
    <>
      {messageContext}
      <div className="page-heading talent-page-heading">
        <div>
          <Title level={2}>企业人才库</Title>
          <Text type="secondary">
            {activeView === 'candidates'
              ? `${memberships.data?.total ?? 0} 条有效人才关系`
              : `${groups.data?.total ?? 0} 个人才分组`}
          </Text>
        </div>
        {activeView === 'groups' && canWrite && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openGroupEditor()}>
            新建分组
          </Button>
        )}
      </div>

      <Tabs
        className="talent-page-tabs"
        activeKey={activeView}
        onChange={(key) => setSearchParams(key === 'groups' ? { view: 'groups' } : {})}
        items={[
          { key: 'candidates', label: '候选人' },
          { key: 'groups', label: '分组' },
        ]}
      />

      {activeView === 'candidates' && (
        <section className="talent-page-section" aria-label="人才候选人">
          <div className="talent-toolbar">
            <Input.Search
              aria-label="搜索人才候选人"
              allowClear
              enterButton={<SearchOutlined />}
              placeholder={canWrite ? '姓名、编号、电话或邮箱' : '姓名或候选人编号'}
              value={memberSearchDraft}
              onChange={(event) => setMemberSearchDraft(event.target.value)}
              onSearch={(value) => {
                setMemberSearch(value.trim())
                setMemberPage(1)
              }}
            />
            <Select
              aria-label="筛选人才分组"
              allowClear
              placeholder="全部分组"
              value={memberGroupId}
              options={(groupOptions.data?.items ?? [])
                .filter((group) => !group.is_archived)
                .map((group) => ({ value: group.id, label: group.name }))}
              onChange={(value) => {
                setMemberGroupId(value)
                setMemberPage(1)
              }}
            />
            <Segmented<TalentPoolMembershipStatus>
              aria-label="人才成员状态"
              value={memberStatus}
              options={[
                { label: '当前人才', value: 'active' },
                { label: '已移出', value: 'removed' },
                { label: '全部', value: 'all' },
              ]}
              onChange={(value) => {
                setMemberStatus(value)
                setMemberPage(1)
              }}
            />
            <Button
              aria-label="刷新人才候选人"
              icon={<ReloadOutlined />}
              loading={memberships.isFetching}
              onClick={() => void memberships.refetch()}
            />
          </div>
          {memberships.isError && (
            <Alert
              type="error"
              showIcon
              message="人才候选人读取失败"
              description={errorMessage(memberships.error, '请稍后重试')}
            />
          )}
          <Table<TalentPoolMembershipRecord>
            rowKey="id"
            columns={memberColumns}
            dataSource={memberships.data?.items ?? []}
            loading={memberships.isPending}
            scroll={{ x: 900 }}
            pagination={{
              current: memberPage,
              pageSize: PAGE_SIZE,
              total: memberships.data?.total ?? 0,
              showSizeChanger: false,
              onChange: setMemberPage,
            }}
            locale={{ emptyText: <Empty description="暂无人才候选人" /> }}
          />
        </section>
      )}

      {activeView === 'groups' && (
        <section className="talent-page-section" aria-label="人才分组">
          <div className="talent-toolbar">
            <Input.Search
              aria-label="搜索人才分组"
              allowClear
              enterButton={<SearchOutlined />}
              placeholder="搜索分组名称"
              value={groupSearchDraft}
              onChange={(event) => setGroupSearchDraft(event.target.value)}
              onSearch={(value) => {
                setGroupSearch(value.trim())
                setGroupPage(1)
              }}
            />
            <Segmented<TalentPoolGroupStatus>
              aria-label="人才分组状态"
              value={groupStatus}
              options={[
                { label: '有效分组', value: 'active' },
                { label: '已归档', value: 'archived' },
                { label: '全部', value: 'all' },
              ]}
              onChange={(value) => {
                setGroupStatus(value)
                setGroupPage(1)
              }}
            />
            <Button
              aria-label="刷新人才分组"
              icon={<ReloadOutlined />}
              loading={groups.isFetching}
              onClick={() => void groups.refetch()}
            />
          </div>
          {groups.isError && <Alert type="error" showIcon message="人才分组读取失败" />}
          <Table<TalentPoolGroupRecord>
            rowKey="id"
            columns={groupColumns}
            dataSource={groups.data?.items ?? []}
            loading={groups.isPending}
            scroll={{ x: 720 }}
            pagination={{
              current: groupPage,
              pageSize: PAGE_SIZE,
              total: groups.data?.total ?? 0,
              showSizeChanger: false,
              onChange: setGroupPage,
            }}
            locale={{ emptyText: <Empty description="暂无人才分组" /> }}
          />
        </section>
      )}

      <Modal
        open={groupModalOpen}
        title={editingGroup ? '编辑人才分组' : '新建人才分组'}
        okText="保存"
        cancelText="取消"
        confirmLoading={saveGroupMutation.isPending}
        onOk={() => groupForm.submit()}
        onCancel={() => {
          setGroupModalOpen(false)
          setEditingGroup(undefined)
          groupForm.resetFields()
        }}
        destroyOnHidden
      >
        <Form<GroupFormValues>
          form={groupForm}
          layout="vertical"
          onFinish={(values) => saveGroupMutation.mutate(values)}
        >
          <Form.Item
            label="分组名称"
            name="name"
            rules={[{ required: true, whitespace: true, message: '请输入分组名称' }]}
          >
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="分组说明" name="description">
            <Input.TextArea rows={4} maxLength={2_000} showCount />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={Boolean(archivingGroup)}
        title="归档人才分组"
        okText="确认归档"
        cancelText="取消"
        confirmLoading={archiveMutation.isPending}
        okButtonProps={{ disabled: !archiveReason.trim() }}
        onOk={() => archiveMutation.mutate()}
        onCancel={() => {
          setArchivingGroup(undefined)
          setArchiveReason('')
        }}
      >
        <Text strong>{archivingGroup?.name}</Text>
        <Input.TextArea
          className="talent-reason-input"
          aria-label="归档原因"
          rows={4}
          maxLength={2_000}
          showCount
          value={archiveReason}
          placeholder="填写归档原因"
          onChange={(event) => setArchiveReason(event.target.value)}
        />
      </Modal>

      <Modal
        open={Boolean(removingMember)}
        title="移出人才分组"
        okText="确认移出"
        cancelText="取消"
        confirmLoading={removeMutation.isPending}
        okButtonProps={{ disabled: !removeReason.trim() }}
        onOk={() => removeMutation.mutate()}
        onCancel={() => {
          setRemovingMember(undefined)
          setRemoveReason('')
        }}
      >
        <Space>
          <DatabaseOutlined />
          <Text>
            {removingMember?.candidate_name || removingMember?.candidate_code} ·{' '}
            {removingMember?.group_name}
          </Text>
        </Space>
        <Input.TextArea
          className="talent-reason-input"
          aria-label="移出原因"
          rows={4}
          maxLength={2_000}
          showCount
          value={removeReason}
          placeholder="填写移出原因"
          onChange={(event) => setRemoveReason(event.target.value)}
        />
      </Modal>
    </>
  )
}
