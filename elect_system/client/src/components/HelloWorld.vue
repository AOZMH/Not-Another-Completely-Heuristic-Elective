<template>
  <div class="hello">
    <el-row>
         <el-col :span="4">
            <el-button>默认按钮</el-button>
            <el-button type="primary">选课</el-button>
          </el-col>
          <el-col :span="4"><el-input v-model="input" placeholder="请输入内容"></el-input>
            <el-popover placement="bottom"
                        title="是否确认退课"
                        width="200"
                        trigger="click"
                        >
                        <div style="text-align: right; margin: 0">
                          <el-button size="mini" type="text" @click="visible = false">取消</el-button>
                          <el-button type="primary" size="mini" @click="visible = false">确定</el-button>
                        </div>
                <el-button type="danger" slot="reference">退课</el-button>
            </el-popover>
          </el-col>
    </el-row>
    <el-link icon="el-icon-edit">编辑</el-link>
    <el-link>查看<i class="el-icon-view el-icon--right"></i> </el-link>
    <h1>HelloWorld!</h1>
    <h2>Gaoliren</h2>
    <h1>{{ msg }}</h1>
  </div>
</template>

<script>
export default {
  name: 'HelloWorld',
  data () {
    return {
      msg: 'Welcome to Your Vue.js App',
      input: ''
    }
  }
}
</script>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
h1, h2 {
  font-weight: normal;
}
ul {
  list-style-type: none;
  padding: 0;
}
li {
  display: inline-block;
  margin: 0 10px;
}
a {
  color: #42b983;
}
</style>
