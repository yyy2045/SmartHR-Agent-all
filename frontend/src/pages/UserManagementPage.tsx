import { EditOutlined, KeyOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useState } from 'react'

import {
  ApiError,
  createUser,
  fetchUsers,
  resetUserPassword,
  updateUser,
  type ManagedUser,
  type RoleKey,
  type UserCreateInput,
  type UserUpdateInput,
} from '../api/client'

const { Title, Text } = Typography
const roleOptions: { label: string; value: RoleKey }[] = [
  { label: '企业管理员', value: 'administrator' },
  { label: '招聘专员', value: 'recruiter' },
  { label: '用人经理', value: 'hiring_manager' },
  { label: '审批人', value: 'approver' },
]
const roleLabels = Object.fromEntries(roleOptions.map((item) => [item.value, item.label])) as Record<
  RoleKey,
  string
>

interface ResetPasswordValues {
  temporary_password: string
}

export function UserManagementPage() {
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const [createOpen, setCreateOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<ManagedUser | null>(null)
  const [resettingUser, setResettingUser] = useState<ManagedUser | null>(null)
  const [createForm] = Form.useForm<UserCreateInput>()
  const [editForm] = Form.useForm<UserUpdateInput>()
  const [resetForm] = Form.useForm<ResetPasswordValues>()
  const users = useQuery({ queryKey: ['users'], queryFn: fetchUsers })

  async function refreshUsers() {
    await queryClient.invalidateQueries({ queryKey: ['users'] })
  }

  const createMutation = useMutation({
    mutationFn: createUser,
    onSuccess: async () => {
      await refreshUsers()
      setCreateOpen(false)
      createForm.resetFields()
      messageApi.success('用户已创建')
    },
  })
  const updateMutation = useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: UserUpdateInput }) =>
      updateUser(userId, payload),
    onSuccess: async () => {
      await refreshUsers()
      setEditingUser(null)
      editForm.resetFields()
      messageApi.success('用户已更新')
    },
  })
  const resetMutation = useMutation({
    mutationFn: ({ userId, password }: { userId: string; password: string }) =>
      resetUserPassword(userId, password),
    onSuccess: async () => {
      await refreshUsers()
      setResettingUser(null)
      resetForm.resetFields()
      messageApi.success('临时密码已重置')
    },
  })
  const mutationError = createMutation.error ?? updateMutation.error ?? resetMutation.error

  function openEdit(user: ManagedUser) {
    setEditingUser(user)
    editForm.setFieldsValue({
      display_name: user.display_name,
      is_active: user.is_active,
      roles: user.roles,
    })
  }

  return (
    <>
      {contextHolder}
      <div className="page-heading">
        <div>
          <Title level={2}>用户与权限</Title>
          <Text type="secondary">管理企业账号、固定角色和登录状态</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          创建用户
        </Button>
      </div>

      {mutationError && (
        <Alert
          type="error"
          showIcon
          closable
          className="page-alert"
          message={mutationError instanceof ApiError ? mutationError.message : '用户操作失败'}
        />
      )}

      {users.isError && (
        <Alert
          type="error"
          showIcon
          className="page-alert"
          message="无法读取用户列表"
          description={users.error.message}
          action={<Button onClick={() => void users.refetch()}>重试</Button>}
        />
      )}

      <section className="panel-card user-table-panel">
        <Table<ManagedUser>
          rowKey="id"
          loading={users.isPending}
          dataSource={users.data ?? []}
          pagination={false}
          locale={{ emptyText: '暂无用户' }}
          scroll={{ x: 780 }}
          columns={[
            {
              title: '用户',
              key: 'user',
              render: (_, user) => (
                <div className="user-identity-cell">
                  <Text strong>{user.display_name}</Text>
                  <Text type="secondary">{user.username}</Text>
                </div>
              ),
            },
            {
              title: '角色',
              dataIndex: 'roles',
              render: (roles: RoleKey[]) => (
                <Space size={[4, 4]} wrap>
                  {roles.map((role) => (
                    <Tag key={role} color={role === 'administrator' ? 'gold' : 'blue'}>
                      {roleLabels[role]}
                    </Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: '账号状态',
              key: 'status',
              width: 140,
              render: (_, user) => (
                <Space direction="vertical" size={2}>
                  <Tag color={user.is_active ? 'success' : 'default'}>
                    {user.is_active ? '已启用' : '已停用'}
                  </Tag>
                  {user.must_change_password && <Text type="warning">等待首次改密</Text>}
                </Space>
              ),
            },
            {
              title: '操作',
              key: 'actions',
              width: 210,
              render: (_, user) => (
                <Space>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(user)}>
                    编辑
                  </Button>
                  <Button
                    size="small"
                    icon={<KeyOutlined />}
                    onClick={() => setResettingUser(user)}
                  >
                    重置密码
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </section>

      <Modal
        title="创建用户"
        open={createOpen}
        okText="创建"
        cancelText="取消"
        confirmLoading={createMutation.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
      >
        <Form<UserCreateInput>
          form={createForm}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => createMutation.mutate(values)}
        >
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input autoComplete="off" maxLength={64} />
          </Form.Item>
          <Form.Item label="姓名" name="display_name" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            label="临时密码"
            name="temporary_password"
            rules={[{ required: true, min: 8, message: '临时密码至少 8 位' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item label="角色" name="roles" rules={[{ required: true, message: '至少选择一个角色' }]}>
            <Checkbox.Group options={roleOptions} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑用户${editingUser ? ` · ${editingUser.display_name}` : ''}`}
        open={Boolean(editingUser)}
        okText="保存"
        cancelText="取消"
        confirmLoading={updateMutation.isPending}
        onCancel={() => setEditingUser(null)}
        onOk={() => editForm.submit()}
      >
        <Form<UserUpdateInput>
          form={editForm}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => {
            if (editingUser) updateMutation.mutate({ userId: editingUser.id, payload: values })
          }}
        >
          <Form.Item label="姓名" name="display_name" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="角色" name="roles" rules={[{ required: true, message: '至少选择一个角色' }]}>
            <Checkbox.Group options={roleOptions} />
          </Form.Item>
          <Form.Item label="启用账号" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置临时密码${resettingUser ? ` · ${resettingUser.display_name}` : ''}`}
        open={Boolean(resettingUser)}
        okText="确认重置"
        cancelText="取消"
        confirmLoading={resetMutation.isPending}
        onCancel={() => setResettingUser(null)}
        onOk={() => resetForm.submit()}
      >
        <Form<ResetPasswordValues>
          form={resetForm}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => {
            if (resettingUser) {
              resetMutation.mutate({
                userId: resettingUser.id,
                password: values.temporary_password,
              })
            }
          }}
        >
          <Alert
            type="warning"
            showIcon
            message="重置后该用户的现有会话将立即失效，下次登录必须修改临时密码。"
            className="form-alert"
          />
          <Form.Item
            label="新临时密码"
            name="temporary_password"
            rules={[{ required: true, min: 8, message: '临时密码至少 8 位' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
